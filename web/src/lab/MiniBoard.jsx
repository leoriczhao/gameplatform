const BOARDS = {
  snake: {
    cols: 14,
    rows: 7,
    tag: "LIVE PREVIEW",
    cells: [
      [2, 3, "lime-dim"], [3, 3, "lime-dim"], [4, 3, "lime-dim"],
      [5, 3, "lime-dim"], [5, 2, "lime-dim"], [5, 1, "lime-dim"],
      [6, 1, "lime-dim"], [7, 1, "lime"], [11, 2, "red", "round"],
    ],
  },
  tetris: {
    cols: 12,
    rows: 8,
    tag: "LIVE PREVIEW",
    cells: [
      [2, 7, "cyan"], [3, 7, "cyan"], [4, 7, "cyan"], [2, 6, "cyan"],
      [3, 6, "cyan"], [4, 6, "violet"], [5, 6, "violet"], [6, 6, "violet"],
      [7, 6, "amber"], [8, 6, "amber"], [8, 5, "amber"], [7, 5, "green"],
      [8, 4, "green"], [5, 1, "lime"], [6, 1, "lime"], [5, 2, "lime"],
      [6, 2, "lime"],
    ],
  },
  microrts: {
    cols: 14,
    rows: 7,
    tag: "LIVE PREVIEW",
    cells: [
      [2, 2, "lime", "round"], [3, 4, "lime", "round"], [6, 3, "lime", "round"],
      [10, 5, "red", "round"], [9, 3, "red", "round"], [11, 1, "amber", "round"],
      [4, 5, "terrain"], [5, 5, "terrain"], [6, 5, "terrain"], [9, 1, "terrain"],
      [10, 1, "terrain"], [10, 2, "terrain"],
    ],
  },
};

const FALLBACK = {
  cols: 12,
  rows: 6,
  tag: "ENVIRONMENT",
  cells: [
    [2, 2, "lime-dim"], [3, 2, "lime-dim"], [4, 2, "lime"], [3, 3, "lime-dim"],
    [8, 3, "violet"], [9, 3, "violet"], [9, 4, "violet"], [6, 4, "cyan"],
  ],
};

export default function MiniBoard({ game, size = "", tag, className = "" }) {
  const def = BOARDS[game] || FALLBACK;
  const cells = new Map(def.cells.map(([c, r, tone, shape]) => [`${c}:${r}`, { tone, shape }]));
  const rows = [];
  for (let r = 0; r < def.rows; r += 1) {
    for (let c = 0; c < def.cols; c += 1) {
      const hit = cells.get(`${c}:${r}`);
      const classes = ["lab-mini__cell"];
      classes.push(hit ? `lab-mini__cell--${hit.tone}` : "lab-mini__cell--grid");
      if (hit && hit.shape === "round") classes.push("lab-mini__cell--round");
      rows.push(<span key={`${c}:${r}`} className={classes.join(" ")} />);
    }
  }
  const tagText = tag === undefined ? def.tag : tag;
  return (
    <div
      className={`lab-mini ${size === "lg" ? "lab-mini--lg" : ""} ${size === "sm" ? "lab-mini--sm" : ""} ${className}`}
      style={{ "--mini-w": def.cols, "--mini-h": def.rows }}
      role="img"
      aria-label={`${game || "environment"} board preview`}
    >
      {tagText ? <span className="lab-mini-tag">{tagText}</span> : null}
      {rows}
    </div>
  );
}
