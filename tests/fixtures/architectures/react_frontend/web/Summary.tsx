export function Summary(props: { total: number; title: string }) {
  return (
    <p>
      {props.title}: {props.total}
    </p>
  );
}
