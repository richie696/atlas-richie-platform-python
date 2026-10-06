/**
 * 最小 PNG 读取器与像素差异比较。
 *
 * 中文
 * ----
 * 只支持 Chrome headless 截图实际会产生的组合：8 位色深、colorType 2(RGB)或
 * 6(RGBA)、非隔行。用 Node 内置 `zlib` 解压 IDAT，不引入任何依赖——
 * 这个视觉门禁必须保持零新增依赖，否则它会因为装不上工具而被跳过。
 *
 * 为什么需要像素级容差而不是直接比文件摘要：抗锯齿与字体栅格化在**跨进程**的
 * Chrome 启动之间会有极少量抖动（实测同一页面两次捕获最多 89 个像素、占
 * 0.0077%、最大通道差 44），而真实布局回归的量级是 7849 像素、0.68%、最大
 * 通道差 233。两者相差三个数量级，用阈值区分是可靠的。
 */
import { readFileSync } from "node:fs";
import { inflateSync } from "node:zlib";

const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

/** 读取 PNG 像素，返回 {width, height, channels, data}。 */
export function readPng(filePath) {
  const buffer = readFileSync(filePath);
  if (!buffer.subarray(0, 8).equals(PNG_SIGNATURE)) {
    throw new TypeError(`不是 PNG 文件: ${filePath}`);
  }

  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  let interlace = 0;
  const idat = [];

  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString("ascii", offset + 4, offset + 8);
    const dataStart = offset + 8;
    if (type === "IHDR") {
      width = buffer.readUInt32BE(dataStart);
      height = buffer.readUInt32BE(dataStart + 4);
      bitDepth = buffer[dataStart + 8];
      colorType = buffer[dataStart + 9];
      interlace = buffer[dataStart + 12];
    } else if (type === "IDAT") {
      idat.push(buffer.subarray(dataStart, dataStart + length));
    } else if (type === "IEND") {
      break;
    }
    offset = dataStart + length + 4; // 跳过 CRC
  }

  if (bitDepth !== 8) throw new TypeError(`不支持的位深 ${bitDepth}: ${filePath}`);
  if (colorType !== 2 && colorType !== 6) {
    throw new TypeError(`不支持的颜色类型 ${colorType}: ${filePath}`);
  }
  if (interlace !== 0) throw new TypeError(`不支持隔行 PNG: ${filePath}`);

  const channels = colorType === 6 ? 4 : 3;
  const raw = inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const pixels = Buffer.alloc(height * stride);

  // 逐扫描线反滤波（PNG filter 0-4）
  for (let y = 0; y < height; y += 1) {
    const filter = raw[y * (stride + 1)];
    const lineStart = y * (stride + 1) + 1;
    const outStart = y * stride;
    for (let x = 0; x < stride; x += 1) {
      const rawByte = raw[lineStart + x];
      const left = x >= channels ? pixels[outStart + x - channels] : 0;
      const up = y > 0 ? pixels[outStart - stride + x] : 0;
      const upLeft = y > 0 && x >= channels ? pixels[outStart - stride + x - channels] : 0;
      let value;
      switch (filter) {
        case 0: value = rawByte; break;
        case 1: value = rawByte + left; break;
        case 2: value = rawByte + up; break;
        case 3: value = rawByte + ((left + up) >> 1); break;
        case 4: {
          const p = left + up - upLeft;
          const pa = Math.abs(p - left);
          const pb = Math.abs(p - up);
          const pc = Math.abs(p - upLeft);
          const predictor = pa <= pb && pa <= pc ? left : pb <= pc ? up : upLeft;
          value = rawByte + predictor;
          break;
        }
        default: throw new TypeError(`未知的 PNG filter ${filter}`);
      }
      pixels[outStart + x] = value & 0xff;
    }
  }

  return { width, height, channels, data: pixels };
}

/**
 * 比较两张 PNG 的像素。
 *
 * 返回差异统计。`identical` 为 true 时直接跳过像素扫描，用于绝大多数未改动用例。
 */
export function diffPng(baselinePath, candidatePath, tolerance) {
  const base = readPng(baselinePath);
  const next = readPng(candidatePath);
  if (base.width !== next.width || base.height !== next.height) {
    return {
      identical: false,
      sizeMismatch: true,
      baselineSize: `${base.width}x${base.height}`,
      candidateSize: `${next.width}x${next.height}`,
      differing: base.width * base.height,
      total: base.width * base.height,
      ratio: 1,
      maxDelta: 255,
      bbox: null,
      beyondTolerance: true,
    };
  }

  const total = base.width * base.height;
  let differing = 0;
  let maxDelta = 0;
  let minX = base.width;
  let minY = base.height;
  let maxX = -1;
  let maxY = -1;

  for (let y = 0; y < base.height; y += 1) {
    for (let x = 0; x < base.width; x += 1) {
      const i = (y * base.width + x) * base.channels;
      const delta = Math.max(
        Math.abs(base.data[i] - next.data[i]),
        Math.abs(base.data[i + 1] - next.data[i + 1]),
        Math.abs(base.data[i + 2] - next.data[i + 2]),
      );
      if (delta === 0) continue;
      differing += 1;
      if (delta > maxDelta) maxDelta = delta;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }

  const ratio = differing / total;
  return {
    identical: differing === 0,
    sizeMismatch: false,
    differing,
    total,
    ratio,
    maxDelta,
    bbox: maxX < 0 ? null : [minX, minY, maxX + 1, maxY + 1],
    // 两个条件任一超限即判为回归：单看比例会漏掉「小面积但对比极大」的错位，
    // 单看最大差会把抗锯齿误判为回归。
    beyondTolerance: ratio > tolerance.ratio || maxDelta > tolerance.maxDelta,
  };
}

/** 默认容差。ratio 取实测抖动上限（0.0077%）的 6 倍，maxDelta 取其 1.8 倍。 */
export const DEFAULT_TOLERANCE = Object.freeze({ ratio: 0.0005, maxDelta: 80 });
