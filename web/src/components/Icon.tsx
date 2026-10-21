import type { SVGProps } from "react";
const icons = {
  layers: ["m12 3 9 5-9 5-9-5 9-5Z", "m3 12 9 5 9-5", "m3 16 9 5 9-5"],
  code: ["m8 8-4 4 4 4", "m16 8 4 4-4 4", "m14 4-4 16"],
  book: [
    "M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4V4Z",
    "M13 7a3 3 0 0 1 3-3h5v15h-5a4 4 0 0 0-3 2",
  ],
  save: ["M5 3h12l4 4v14H3V3h2Z", "M7 3v6h10V3", "M7 21v-8h10v8"],
  play: ["m8 5 11 7-11 7V5Z"],
  search: ["M19 19l-4-4", "M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0Z"],
  region: ["M8 3H3v5", "M16 3h5v5", "M21 16v5h-5", "M8 21H3v-5", "M8 8h8v8H8z"],
  pin: [
    "M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0Z",
    "M15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  ],
  upload: ["M12 16V3", "m7 8 5-5 5 5", "M4 15v6h16v-6"],
  arrow: ["M4 12h16", "m14 6 6 6-6 6"],
  terminal: ["m5 6 6 6-6 6", "M13 18h6"],
  refresh: ["M20 7V3l-4 4", "M20 7A8 8 0 1 0 21 14"],
  lock: ["M6 10h12v11H6z", "M8 10V6a4 4 0 0 1 8 0v4"],
  logout: ["M10 4H4v16h6", "M9 12h12", "m17 8 4 4-4 4"],
  folder: ["M3 6V4h7l2 3h9v13H3V6Z"],
  download: ["M12 3v12", "m7 10 5 5 5-5", "M4 16v5h16v-5"],
  map: ["m3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2V5Z", "M9 3v16", "M15 5v16"],
  clock: ["M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z", "M12 7v5l3 2"],
  x: ["m6 6 12 12", "M18 6 6 18"],
  flow: ["M4 3h6v6H4z", "M14 15h6v6h-6z", "M7 9v9h7", "M16 3h4v6h-4z"],
} as const;
export type IconName = keyof typeof icons;
export default function Icon({
  name,
  ...props
}: SVGProps<SVGSVGElement> & { name: IconName }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {icons[name].map((d, i) => (
        <path d={d} key={i} />
      ))}
    </svg>
  );
}
