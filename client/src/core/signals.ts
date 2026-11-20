/** A small signal core: enough for route, loading and bus state. */

type Subscriber = () => void;

let activeEffect: (() => void) | null = null;
const pending = new Set<Subscriber>();
let scheduled = false;

function schedule(subscriber: Subscriber): void {
  pending.add(subscriber);
  if (scheduled) return;
  scheduled = true;
  queueMicrotask(() => {
    scheduled = false;
    const work = Array.from(pending);
    pending.clear();
    for (const item of work) item();
  });
}

export class Signal<T> {
  private subscribers = new Set<Subscriber>();

  constructor(private current: T) {}

  get value(): T {
    if (activeEffect) this.subscribers.add(activeEffect);
    return this.current;
  }

  set value(next: T) {
    if (Object.is(next, this.current)) return;
    this.current = next;
    for (const subscriber of this.subscribers) schedule(subscriber);
  }

  update(fn: (value: T) => T): void {
    this.value = fn(this.value);
  }
}

export function signal<T>(initial: T): Signal<T> {
  return new Signal(initial);
}

export function effect(fn: () => void): () => void {
  const run = () => {
    const previous = activeEffect;
    activeEffect = run;
    try {
      fn();
    } finally {
      activeEffect = previous;
    }
  };
  run();
  return () => {
    /* effects live for the page; the return value is for API symmetry */
  };
}
