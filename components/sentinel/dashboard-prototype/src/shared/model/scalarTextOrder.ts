/** Locale-independent Unicode scalar ordering, shared by server-page validators. Never re-sort a paginated response. */
export function compareScalarText(first: string, second: string): number {
  const left = Array.from(first),
    right = Array.from(second);
  for (let index = 0; index < Math.min(left.length, right.length); index++) {
    const difference = left[index].codePointAt(0)! - right[index].codePointAt(0)!;
    if (difference !== 0) return difference;
  }
  return left.length - right.length;
}
