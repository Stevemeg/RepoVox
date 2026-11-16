export async function listOrders(): Promise<unknown> {
  const response = await fetch("/api/orders");
  return response.json();
}
