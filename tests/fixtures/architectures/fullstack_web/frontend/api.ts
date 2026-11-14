export async function loadItems(): Promise<string[]> {
  const response = await fetch("/api/items");
  return response.json();
}
