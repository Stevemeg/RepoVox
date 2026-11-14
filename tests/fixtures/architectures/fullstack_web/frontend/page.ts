import { loadItems } from "./api";

export async function renderPage(target: { textContent: string }): Promise<void> {
  const items = await loadItems();
  target.textContent = items.join(", ");
}
