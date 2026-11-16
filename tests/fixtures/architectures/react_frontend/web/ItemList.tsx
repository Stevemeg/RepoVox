import { ItemRow } from "./ItemRow";

export function ItemList(props: { items: string[] }) {
  return (
    <ul>
      {props.items.map((item) => (
        <ItemRow key={item} label={item} />
      ))}
    </ul>
  );
}
