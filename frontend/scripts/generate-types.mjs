import { readFile, writeFile } from "node:fs/promises";
import { compile } from "json-schema-to-typescript";

const schema = JSON.parse(
  await readFile(
    new URL("../src/api/dashboard.schema.json", import.meta.url),
    "utf8",
  ),
);
const types = await compile(schema, "LiveDashboardSnapshot", {
  bannerComment:
    "/* Generated from the backend serialization schema. Run npm run types. */",
  additionalProperties: false,
  style: { bracketSpacing: true, printWidth: 80, trailingComma: "all" },
});
await writeFile(new URL("../src/types/generated.ts", import.meta.url), types);
