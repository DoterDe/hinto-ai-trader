"""One ordered SQLite worker and truthful in-memory durability publication."""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from src.application.paper_persistence_codec import CheckpointCodec, CheckpointCorrupt, CheckpointIncompatible
from src.application.paper_persistence_settings import PaperPersistenceSettings
from src.application.paper_recovery_state import capture, compatibility, restore
from src.domain.paper_persistence import ContinuityFence, PersistenceSnapshot, PersistenceStatus as Status
from src.infrastructure.sqlite_paper_store import DurablePaperStore


class PaperPersistence:
    def __init__(self, settings: PaperPersistenceSettings) -> None:
        self.settings = settings
        self.store = DurablePaperStore(settings)
        self.worker: ThreadPoolExecutor | None = None
        self.ready = False
        self.halted = False
        self.state = PersistenceSnapshot(enabled=settings.enabled,
            status=Status.RECOVERING if settings.enabled else Status.DISABLED, database_healthy=False)

    async def _call(self, function, *args, **kwargs):
        future = asyncio.get_running_loop().run_in_executor(self.worker, lambda: function(*args, **kwargs))
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # Cancellation must not abandon a still-writing thread. Commit or
            # rollback settles before the caller can close/reopen this database.
            try:
                await asyncio.shield(future)
            finally:
                raise

    async def start(self, runtime) -> bool:
        if self.ready:
            return not self.halted
        self.ready = True
        if not self.settings.enabled:
            return True
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='paper-store')
        try:
            await self._call(self.store.open)
            envelope = await self._call(self.store.load)
            if envelope is not None:
                checkpoint = CheckpointCodec.decode(envelope)
                if checkpoint.compatibility != compatibility(runtime):
                    raise CheckpointIncompatible('paper configuration mismatch')
                if checkpoint.checkpoint_at > runtime.clock.now():
                    raise CheckpointIncompatible('runtime clock precedes checkpoint')
                try:
                    await restore(runtime, checkpoint)
                    fence = await self._call(self.store.load_fence)
                    if fence is not None:
                        if (fence.checkpoint_id != envelope.checkpoint_id or fence.watermark < checkpoint.durable_boundary
                                or fence.generation < checkpoint.generation or fence.observed_at < checkpoint.durable_boundary):
                            raise ValueError('inconsistent continuity fence')
                        runtime.portfolio.invalidate()
                        runtime.batcher.watermark = fence.watermark
                        runtime._admission_floor = fence.watermark
                        runtime._generation = fence.generation
                        runtime._last_problem = fence.reason
                except ValueError as exc:
                    raise CheckpointCorrupt('impossible recovered paper state') from exc
                counts = await self._call(self.store.counts)
                self.state = self.state.model_copy(update={'status': Status.RECOVERED, 'database_healthy': True,
                    'session_id': checkpoint.session_id, 'session_created_at': checkpoint.session_created_at,
                    'recovered': True, 'configuration_compatible': True, 'durable_boundary': checkpoint.durable_boundary,
                    'checkpoint_at': checkpoint.checkpoint_at, 'checkpoint_id': envelope.checkpoint_id,
                    'checksum': envelope.checksum, 'retained_checkpoints': counts[0], 'retained_audit_events': counts[1],
                    'reason': 'recovered_continuity_loss' if fence is not None else None})
                return True
            self.state = self.state.model_copy(update={'status': Status.NEW_SESSION, 'database_healthy': True,
                'session_id': 'session_' + uuid4().hex, 'session_created_at': runtime.clock.now(),
                'configuration_compatible': True})
            return True
        except asyncio.CancelledError:
            await runtime.analysis.stop()
            await self.close()
            raise
        except Exception as exc:
            await runtime.analysis.stop()
            runtime.portfolio._failed = True
            self.fail(exc, recovery=True)
            return False

    def fail(self, exc: Exception, *, recovery=False) -> None:
        status = (Status.INCOMPATIBLE if isinstance(exc, CheckpointIncompatible) else
            Status.CORRUPT if isinstance(exc, (CheckpointCorrupt, sqlite3.DatabaseError)) and not isinstance(exc, sqlite3.OperationalError)
            else Status.ERROR if recovery else Status.DEGRADED)
        self.halted = True
        self.state = self.state.model_copy(update={'status': status, 'reason': 'recovery_' + status.value.lower()
            if recovery else 'checkpoint_failed', 'database_healthy': False,
            'configuration_compatible': False if status == Status.INCOMPATIBLE else self.state.configuration_compatible,
            'has_uncommitted_changes': not recovery})

    async def checkpoint(self, runtime) -> None:
        if not self.settings.enabled:
            return
        if self.halted or not self.ready:
            raise RuntimeError('paper persistence unavailable')
        try:
            checkpoint = capture(runtime, self.state.session_id, self.state.session_created_at)
            envelope = CheckpointCodec.encode(checkpoint)
            self.state = self.state.model_copy(update={'has_uncommitted_changes': True})
            counts = await self._call(self.store.commit, envelope, expected=self.state.checkpoint_id)
            self.state = self.state.model_copy(update={'status': Status.DURABLE, 'reason': None, 'database_healthy': True,
                'durable_boundary': checkpoint.durable_boundary, 'checkpoint_at': checkpoint.checkpoint_at,
                'checkpoint_id': envelope.checkpoint_id, 'checksum': envelope.checksum,
                'retained_checkpoints': counts[0], 'retained_audit_events': counts[1], 'has_uncommitted_changes': False})
        except asyncio.CancelledError:
            raise

        except Exception as exc:
            self.fail(exc)
            raise

    async def fence(self, runtime) -> None:
        if not self.settings.enabled or self.state.checkpoint_id is None:
            return
        if self.halted:
            raise RuntimeError('paper persistence unavailable')
        try:
            fence = ContinuityFence(checkpoint_id=self.state.checkpoint_id,
                watermark=max(runtime.batcher.watermark or self.state.durable_boundary, self.state.durable_boundary),
                generation=runtime._generation, reason=runtime._last_problem or 'continuity_lost', observed_at=runtime.clock.now())
            self.state = self.state.model_copy(update={'has_uncommitted_changes': True})
            counts = await self._call(self.store.save_fence, fence)
            self.state = self.state.model_copy(update={'retained_checkpoints': counts[0], 'retained_audit_events': counts[1],
                'has_uncommitted_changes': False, 'reason': 'continuity_loss_saved'})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.fail(exc)
            raise

    async def close(self) -> None:
        if self.worker is not None:
            try:
                await self._call(self.store.close)
            finally:
                self.worker.shutdown(wait=True, cancel_futures=True)
                self.worker = None

    def snapshot(self, boundary) -> PersistenceSnapshot:
        return self.state.model_copy(update={'in_memory_boundary': boundary,
            'has_uncommitted_changes': self.state.has_uncommitted_changes or
                (self.settings.enabled and boundary != self.state.durable_boundary)})
