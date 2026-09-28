import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { violations } from "./check-boundaries.ts";

const root = fileURLToPath(new URL("../src", import.meta.url));
const files = readdirSync(root, { recursive: true }).map(String).filter((file) => /\.[jt]sx?$/.test(file));
if (!files.length) throw new Error("No Web source files found");
const errors = files.flatMap((file) => violations(readFileSync(resolve(root, file), "utf8"), resolve(root, file), root));
errors.forEach((error) => console.error(error));
process.exitCode = errors.length ? 1 : 0;
