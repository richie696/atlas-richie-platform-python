import assert from "node:assert/strict";
import { it } from "node:test";
import { ESLint } from "eslint";

const eslint = new ESLint();

/** Exercise the real flat config with a TSX path, not a separately invented lint configuration. */
async function messages(source) {
  const [result] = await eslint.lintText(source, { filePath: "src/HooksGateProbe.tsx" });
  return result.messages;
}

it("F0.5 rejects Hooks inside event callbacks", async () => {
  const found = await messages(`
    import { useState } from 'react';
    export function Probe() { return <button onClick={() => useState(0)}>create</button>; }
  `);
  assert.ok(found.some(item => item.ruleId === "react-hooks/rules-of-hooks" && item.severity === 2));
});

it("F0.5 rejects stale effect dependencies", async () => {
  const found = await messages(`
    import { useEffect } from 'react';
    export function Probe({ value }: { value: string }) {
      useEffect(() => { console.log(value); }, []);
      return null;
    }
  `);
  assert.ok(found.some(item => item.ruleId === "react-hooks/exhaustive-deps" && item.severity === 2));
});

it("F0.5 parses TypeScript/TSX and accepts unconditional Hooks with complete dependencies", async () => {
  assert.deepEqual(await messages(`
    import { useEffect, useState } from 'react';
    export function Probe({ value }: { value: string }) {
      const [enabled] = useState<boolean>(true);
      useEffect(() => { console.log(value); }, [value]);
      return enabled ? <span>{value}</span> : null;
    }
  `), []);
});

it("F5 rejects mutation of component inputs, including nested test controls", async () => {
  const found = await messages(`
    export function Probe({control}: {control: {mode: string}}) {
      return <button onClick={() => {control.mode = 'changed';}}>change</button>;
    }
  `);
  assert.ok(found.some(item => item.ruleId === "react-hooks/immutability" && item.severity === 2));
});

it("F5 rejects nondeterministic render and synchronous state derivation in effects", async () => {
  const impure = await messages(`
    export function Probe() {return <span>{Date.now()}</span>;}
  `);
  assert.ok(impure.some(item => item.ruleId === "react-hooks/purity" && item.severity === 2));
  const derived = await messages(`
    import {useEffect,useState} from 'react';
    export function Probe({value}: {value: string}) {
      const [copy,setCopy] = useState('');
      useEffect(() => {setCopy(value);}, [value]);
      return <span>{copy}</span>;
    }
  `);
  assert.ok(derived.some(item => item.ruleId === "react-hooks/set-state-in-effect" && item.severity === 2));
});

it("F5 accepts private effect-owner commands without mutating component inputs", async () => {
  assert.deepEqual(await messages(`
    import {useMemo} from 'react';
    function createOwner() {
      let mode = 'initial';
      return Object.freeze({change: () => {mode = 'changed';}, read: () => mode});
    }
    export function Probe() {
      const owner = useMemo(() => createOwner(), []);
      return <button onClick={owner.change}>change</button>;
    }
  `), []);
});
