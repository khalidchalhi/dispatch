import { PageIntro } from "@/components/patterns/page-intro";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { ListsManager } from "./_components/lists-manager";
import { toList, type ApiListCollectionResponse } from "./_lib/lists-api";

export default async function ListsPage() {
  const response = await serverJson<ApiListCollectionResponse>(ENDPOINTS.lists.list);
  const lists = response.items.map(toList);

  return (
    <div className="page-stack">
      <PageIntro
        title="Lists"
        description="Organize contacts into named lists and use them to target campaign sends."
      />
      <ListsManager initialLists={lists} />
    </div>
  );
}
