export async function loadItems(tag: string): Promise<string[]> {
  const response = await fetch(`/api/items?tag=${tag}`);
  return response.json();
}
