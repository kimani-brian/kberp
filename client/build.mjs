import { build, context } from "esbuild";

const options = {
  entryPoints: ["src/index.ts"],
  outfile: "../src/kberp/web/static/js/kwl.js",
  bundle: true,
  format: "iife",
  target: ["es2020"],
  sourcemap: false,
  minify: false,
  logLevel: "info",
};

if (process.argv.includes("--watch")) {
  const ctx = await context(options);
  await ctx.watch();
} else {
  await build(options);
}
