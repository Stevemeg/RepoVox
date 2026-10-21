type Count = number;
function increment(n: Count): Count { return n + 1; }
export function comet(n: Count): Count {
  return increment(n);
}
