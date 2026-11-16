import { loadItems } from "./api";
import { ItemList } from "./ItemList";
import { rank } from "./rank";
import { Summary } from "./Summary";

export async function Page(props: { tag: string }) {
  const items = await loadItems(props.tag);
  const ranked = rank(items);
  return (
    <section>
      <ItemList items={ranked} />
      <Summary total={ranked.length} title={props.tag} />
    </section>
  );
}
