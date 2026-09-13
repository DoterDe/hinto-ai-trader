import { useId, useState } from "react";
import catalog from "./catalog.json";

export const terms = catalog.terms;
export const modules = catalog.modules;
export function term(key: string) {
  return terms.find((item) => item.key === key);
}

export function Help({ name }: { name: string }) {
  const item = term(name);
  const id = useId();
  const [open, setOpen] = useState(false);
  if (!item) throw new Error(`Missing help: ${name}`);
  return (
    <details className="help" open={open}>
      <summary
        aria-label={`About ${item.label}`}
        aria-controls={id}
        aria-expanded={open}
        onClick={(event) => {
          event.preventDefault();
          setOpen(!open);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setOpen(!open);
          }
          if (event.key === "Escape") {
            event.preventDefault();
            setOpen(false);
          }
        }}
      >
        i
      </summary>
      <div className="help-popover" id={id}>
        <strong>{item.label}</strong>
        <p>{item.explanation}</p>
      </div>
    </details>
  );
}
export function Label({ name, text }: { name: string; text?: string }) {
  return (
    <span className="label-help">
      {text ?? term(name)?.label}
      <Help name={name} />
    </span>
  );
}
