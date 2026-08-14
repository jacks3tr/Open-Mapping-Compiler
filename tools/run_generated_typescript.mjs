import { execFileSync } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

function typecheck(generatedPath) {
  const absolute = resolve(generatedPath);
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const compiler = join(root, "node_modules", "typescript", "bin", "tsc");
  try {
    execFileSync(process.execPath, [
      compiler,
      "--ignoreConfig",
      "--noEmit",
      "--strict",
      "--target", "ES2022",
      "--module", "NodeNext",
      "--moduleResolution", "NodeNext",
      "--skipLibCheck",
      "--types", "node",
      absolute,
    ], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  } catch (error) {
    const stderr = error && typeof error === "object" && "stderr" in error ? String(error.stderr) : String(error);
    const stdout = error && typeof error === "object" && "stdout" in error ? String(error.stdout) : "";
    throw new Error(stderr || stdout || String(error));
  }
}

async function runTs(source, serializedInput, selfTest) {
  const dir = await mkdtemp(join(tmpdir(), "open-mapping-ts-"));
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const callerCwd = process.cwd();
  try {
    const generatedPath = join(dir, "generated.ts");
    const runnerPath = join(dir, "runner.mts");
    await writeFile(generatedPath, source, "utf8");
    const body = selfTest
      ? "console.log('ok');\n"
      : `import { transform } from "./generated.ts";\nlet data = "";\nprocess.stdin.setEncoding("utf8");\nprocess.stdin.on("data", (chunk) => (data += chunk));\nprocess.stdin.on("end", () => { const output = transform(JSON.parse(data)); process.stdout.write(JSON.stringify(output)); });\n`;
    await writeFile(runnerPath, body, "utf8");
    const loader = pathToFileURL(join(root, "node_modules", "tsx", "dist", "loader.mjs")).href;
    return execFileSync(process.execPath, ["--import", loader, runnerPath], {
      cwd: callerCwd,
      input: selfTest ? undefined : serializedInput,
      encoding: "utf8",
      stdio: ["pipe", "pipe", "pipe"],
    });
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

async function main() {
  if (process.argv.includes("--self-test")) {
    const dir = await mkdtemp(join(tmpdir(), "open-mapping-ts-self-"));
    try {
      const path = join(dir, "generated.ts");
      await writeFile(path, "export function transform(source: unknown): unknown { return source; }", "utf8");
      typecheck(path);
      process.stdout.write(await runTs(readFileSync(path, "utf8"), null, true));
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
    return;
  }
  if (process.argv[2] === "--typecheck") {
    const generatedPath = process.argv[3];
    if (!generatedPath) {
      process.stderr.write("usage: run_generated_typescript.mjs --typecheck GENERATED.ts\n");
      process.exitCode = 2;
      return;
    }
    try {
      typecheck(generatedPath);
    } catch (error) {
      process.stderr.write(String(error) + "\n");
      process.exitCode = 1;
    }
    return;
  }
  const generatedPath = process.argv[2];
  if (!generatedPath) {
    process.stderr.write("usage: run_generated_typescript.mjs GENERATED.ts\n");
    process.exitCode = 2;
    return;
  }
  const source = readFileSync(generatedPath, "utf8");
  let serializedInput;
  try {
    let data = "";
    process.stdin.setEncoding("utf8");
    for await (const chunk of process.stdin) data += chunk;
    JSON.parse(data);
    serializedInput = data;
  } catch (error) {
    process.stderr.write(String(error) + "\n");
    process.exitCode = 2;
    return;
  }
  try {
    process.stdout.write(await runTs(source, serializedInput, false));
  } catch (error) {
    process.stderr.write(String(error) + "\n");
    process.exitCode = 1;
  }
}

main();
