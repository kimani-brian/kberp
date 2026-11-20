/** Category registry, the KWL analogue of OWL's registry. */

export class Registry {
  private categories = new Map<string, Map<string, unknown>>();

  category<T>(name: string): Map<string, T> {
    let bucket = this.categories.get(name);
    if (!bucket) {
      bucket = new Map();
      this.categories.set(name, bucket);
    }
    return bucket as Map<string, T>;
  }

  add<T>(category: string, name: string, value: T): void {
    this.category<T>(category).set(name, value);
  }

  get<T>(category: string, name: string): T | undefined {
    return this.category<T>(category).get(name);
  }
}

export const registry = new Registry();
