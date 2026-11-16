import { listOrders } from "./api";

export async function showOrders(target: { textContent: string }): Promise<void> {
  const orders = await listOrders();
  target.textContent = String(orders);
}
