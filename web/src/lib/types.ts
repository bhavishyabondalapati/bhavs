export type Title = {
  id: string;
  title: string;
  year: number;
  genres: string[];
  description: string;
  duration_sec?: number;
  status: "PENDING" | "PROCESSING" | "READY" | "FAILED";
  poster_path?: string;
  license_name?: string;
  license_url?: string;
  credit?: string;
};

export type ContinueItem = { title: Title; position: number; duration?: number; updated_at?: number };
export type RecRow = { key: string; label: string; titles: Title[] };
export type Me = { user_id: string; email: string; groups: string[]; is_admin: boolean };
