import { readFile, writeFile } from "node:fs/promises";
import { EOL } from "node:os";
import { compile } from "json-schema-to-typescript";

for (const [source, target, name] of [
  ["dashboard.schema.json", "generated.ts", "LiveDashboardSnapshot"],
  ["validation.schema.json", "validation.generated.ts", "ValidationSnapshot"],
]) {
const schema = JSON.parse(
  await readFile(
    new URL(`../src/api/${source}`, import.meta.url),
    "utf8",
  ),
);
const types = await compile(schema, name, {
  bannerComment:
    "/* Generated from the backend serialization schema. Run npm run types. */",
  additionalProperties: false,
  style: { bracketSpacing: true, printWidth: 80, trailingComma: "all" },
});
const targetUrl = new URL(`../src/types/${target}`, import.meta.url);
if (process.argv.includes("--check")) {
  const current = await readFile(targetUrl, "utf8");
  if (current.replaceAll("\r\n", "\n") !== types.replaceAll("\r\n", "\n"))
    throw new Error(`Outdated generated types: ${target}`);
} else {
  // Match the Windows working-tree convention without changing canonical Git text.
  await writeFile(targetUrl, types.replaceAll("\r\n", "\n").replaceAll("\n", EOL));
}
}
