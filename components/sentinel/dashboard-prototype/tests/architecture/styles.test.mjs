import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { test } from "node:test";
import * as sass from "sass";

const source = fileURLToPath(new URL("../../src/", import.meta.url));
const read = relative => readFileSync(path.join(source, relative), "utf8");
const shellClasses = ["app-shell", "topbar", "brand", "brand-mark", "main-nav", "header-info", "locale-control", "clock", "avatar", "demo-banner", "content", "footer"];

test("F3 stylesheet has one ordered global entry; components import only owned modules", () => {
  const entry = read("core/styles/index.scss");
  assert.deepEqual([...entry.matchAll(/@use "([^"]+)"/g)].map(match => match[1]),
    ["structural-tokens", "skins/dark", "reset", "astryx"]);
  const imports = [];
  const walk = directory => {
    for (const item of readdirSync(directory, {withFileTypes: true})) {
      const file = path.join(directory, item.name);
      if (item.isDirectory()) walk(file);
      else if (/\.tsx?$/.test(item.name)) {
        for (const match of readFileSync(file, "utf8").matchAll(/import\s+[\s\S]*?["']([^"']+\.(?:css|scss))["']/g))
          imports.push({file, specifier: match[1]});
      }
    }
  };
  walk(source);
  const global = imports.filter(item => !item.specifier.endsWith(".module.scss") && !item.specifier.startsWith("@astryxdesign/"));
  assert.deepEqual(global, [{file: path.join(source,"main.tsx"), specifier: "./core/styles/index.scss"}]);
});

test("F3 application chrome has no competing legacy selectors", () => {
  const module = read("app/shell/AppShell.module.scss");
  assert.equal(existsSync(path.join(source,"core/styles/_legacy.scss")), false);
  for (const name of shellClasses) {
    assert.match(module, new RegExp("\\."+name+"(?![\\w-])"), "missing private owner: "+name);
  }
  for (const component of ["AppShell","Header","Navigation","Footer","StatusBanner","UserMenu"])
    assert.match(read("app/shell/"+component+".tsx"), /import styles from "\.\/AppShell\.module\.scss"/);
});

test("F3 private chrome consumes skin tokens; default skin and reset compile together", () => {
  const module = read("app/shell/AppShell.module.scss");
  assert.doesNotMatch(module, /#[0-9a-f]{3,8}\b|\b(?:rgb|hsl)a?\(/i, "private layout embeds skin colors");
  assert.doesNotMatch(module, /var\(--(?:color|font|space|radius|type|motion|layout|layer)-/, "product token collides with vendor namespace");
  assert.match(module, /\.main-nav button svg\s*\{\s*display: none/);
  const skin = read("core/styles/skins/_dark.scss"), structure = read("core/styles/_structural-tokens.scss");
  const definitions = new Set([...(skin+structure).matchAll(/(--[\w-]+)\s*:/g)].map(match=>match[1]));
  for(const match of module.matchAll(/var\((--[\w-]+)/g)) assert.ok(definitions.has(match[1]), "undefined skin token: "+match[1]);
  const css = sass.compile(path.join(source,"core/styles/index.scss")).css;
  assert.match(css, /:root:not\(\[data-sentinel-skin\]\)/);
  assert.match(css, /body\s*\{[\s\S]*?var\(--sentinel-page-background-image\)/);
  assert.doesNotMatch(css, /\.topbar\b/, "module leaked into global entry");
});

test("F3 all migrated presentation modules have scoped ownership and defined skin roles", () => {
  const skin = read("core/styles/skins/_dark.scss"), structure = read("core/styles/_structural-tokens.scss");
  const definitions = new Set([...(skin+structure).matchAll(/(--[\w-]+)\s*:/g)].map(match=>match[1]));
  const modules = [];
  const walk = directory => {
    for (const item of readdirSync(directory, {withFileTypes: true})) {
      const file = path.join(directory, item.name);
      if (item.isDirectory()) walk(file);
      else if (item.name.endsWith(".module.scss")) modules.push(file);
    }
  };
  walk(source);
  assert.ok(modules.length >= 20, "module ownership has regressed into a global stylesheet");
  for (const file of modules) {
    const style = readFileSync(file, "utf8");
    assert.doesNotMatch(style, /#[0-9a-f]{3,8}\b|\b(?:rgb|hsl)a?\(/i, file+" embeds skin colors");
    assert.doesNotMatch(style, /var\(--(?:color|font|space|radius|type|motion|layout|layer)-/, file+" collides with vendor tokens");
    assert.doesNotMatch(style, /^\s*:global\(/m, file+" has an unscoped global selector");
    assert.doesNotMatch(style, /\.astryx-[\w-]+/, file+" spreads vendor markup dependencies outside the adapter");
    for(const match of style.matchAll(/var\((--[\w-]+)/g)) assert.ok(definitions.has(match[1]), file+" has undefined token "+match[1]);
    sass.compile(file);
  }
  assert.equal(existsSync(path.join(source,"core/styles/_legacy.scss")), false, "legacy stylesheet returned");
});

test("F3 vendor field overrides are centralized; feature layout never skins nested native inputs", () => {
  const paths = ["app/shell/AppShell.module.scss", ...["identity/Identity", "rules/Rules", "applications/Applications", "faults/Faults", "overview/Overview", "realtime/Monitoring", "system/System"].map(item=>"features/"+item.split('/')[0]+"/ui/"+item.split('/')[1]+".module.scss")];
  for (const file of paths) {
    const css=read(file).replace(/\/\*[\s\S]*?\*\//g,'');
    assert.doesNotMatch(css, /(?:^|[{}])[^{}]*(?:\s|>)(?:input|select|label)(?:[\s.:#\[>{,]|$)[^{}]*\{/m, file+" reaches into vendor form internals");
  }
  const adapter=read("core/styles/_astryx.scss");
  assert.match(adapter, /Astryx 0\.6\.1 markup dependencies/);
  assert.match(adapter, /input:focus-visible/);
  const root=read("core/styles/_reset.scss");
  const controls = [...root.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter(match=>/\b(?:button|input|select)\b/.test(match[1])).map(match=>match[2]).join('\n');
  assert.doesNotMatch(controls, /(?:background|border-radius|height|padding)\s*:/, "reset must not globally reskin form controls");
});
