import type { NextConfig } from "next";
import path from "node:path";

const config: NextConfig = {
  output:"standalone",
  outputFileTracingRoot:path.resolve(import.meta.dirname,"../.."),
  poweredByHeader:false,
  // Keep SSE delivery independent of an HTTP compression buffer.
  compress:false,
};
export default config;
