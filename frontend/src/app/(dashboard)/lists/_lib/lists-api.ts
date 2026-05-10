import type { List } from "@/types/list";

export type ApiListResponse = {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
  created_at: string;
};

export type ApiListCollectionResponse = {
  items: ApiListResponse[];
};

export function toList(api: ApiListResponse): List {
  return {
    id: api.id,
    name: api.name,
    description: api.description,
    memberCount: api.member_count,
    createdAt: api.created_at,
    updatedAt: api.created_at,
  };
}
