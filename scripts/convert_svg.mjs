#!/usr/bin/env node
// Convert SVG to PNG using sharp with automatic density calculation.
// Usage: node scripts/convert_svg.mjs --input logo.svg --output logo.png --width 1024
import sharp from 'sharp';
import { readFile } from 'fs/promises';
import { resolve, dirname, basename, extname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (key.startsWith('--')) {
      const name = key.slice(2);
      const next = argv[i + 1];
      if (next && !next.startsWith('--')) {
        args[name] = next;
        i++;
      } else {
        args[name] = true;
      }
    } else if (key.startsWith('-') && key.length === 2) {
      const name = { i: 'input', o: 'output', w: 'width', h: 'height', b: 'background' }[key[1]];
      const next = argv[i + 1];
      if (name && next && !next.startsWith('-')) {
        args[name] = next;
        i++;
      }
    }
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (!args.input) {
    console.error('Error: --input is required');
    process.exit(1);
  }

  const inputPath = resolve(args.input);
  const outputPath = args.output
    ? resolve(args.output)
    : join(dirname(inputPath), basename(inputPath, extname(inputPath)) + '.png');

  const svgBuffer = await readFile(inputPath);
  const svgText = svgBuffer.toString('utf-8');

  // Parse viewBox width to compute density.
  const viewBoxMatch = svgText.match(/viewBox=["']\d+\s+\d+\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)["']/);
  const widthMatch = svgText.match(/width=["'](\d+(?:\.\d+)?)[a-z%]*["']/);

  let svgWidth = 100;
  let svgHeight = 100;
  if (viewBoxMatch) {
    svgWidth = parseFloat(viewBoxMatch[1]);
    svgHeight = parseFloat(viewBoxMatch[2]);
  } else if (widthMatch) {
    svgWidth = parseFloat(widthMatch[1]);
    const heightMatch = svgText.match(/height=["'](\d+(?:\.\d+)?)[a-z%]*["']/);
    if (heightMatch) svgHeight = parseFloat(heightMatch[1]);
  }

  const targetWidth = args.width ? parseInt(args.width, 10) : svgWidth;
  const targetHeight = args.height ? parseInt(args.height, 10) : Math.round(targetWidth * (svgHeight / svgWidth));
  const density = Math.max(72, Math.round(72 * targetWidth / svgWidth));

  const pipeline = sharp(svgBuffer, { density })
    .resize(targetWidth, targetHeight, { fit: 'contain', background: args.background || { r: 0, g: 0, b: 0, alpha: 0 } });

  if (args.background) {
    pipeline.flatten({ background: args.background });
  }

  await pipeline.toFile(outputPath);
  console.log(`Converted ${inputPath} -> ${outputPath} (${targetWidth}x${targetHeight}, density=${density})`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
