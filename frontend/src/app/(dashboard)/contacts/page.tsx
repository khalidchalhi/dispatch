import Link from "next/link";
import { Button } from "@/components/ui/button";
import { PageIntro } from "@/components/patterns/page-intro";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import type {
  ContactLifecycle,
  ContactListItem,
  ContactSource,
} from "@/types/contact";
import { lists } from "../lists/_lib/lists-queries";
import { ContactsTable } from "./_components/contacts-table";

type ContactsListApiResponse = {
  items: Array<{
    id: string;
    email: string;
    first_name: string | null;
    last_name: string | null;
    lifecycle_status: string;
    source_type?: string | null;
    created_at: string;
    updated_at: string;
  }>;
};

function toContactLifecycle(value: string): ContactLifecycle {
  if (value === "active") return "active";
  if (value === "bounced") return "bounced";
  if (value === "complained") return "complained";
  if (value === "unsubscribed") return "unsubscribed";
  if (value === "suppressed") return "suppressed";
  if (value === "deleted") return "deleted";
  return "active";
}

function toContactSource(value: string | null | undefined): ContactSource {
  if (value === "csv_import") return "csv_import";
  if (value === "api") return "api";
  if (value === "manual") return "manual";
  if (value === "webhook") return "webhook";
  if (value === "integration") return "api";
  return "manual";
}

function toContactListItem(
  item: ContactsListApiResponse["items"][number],
): ContactListItem {
  return {
    id: item.id,
    email: item.email,
    firstName: item.first_name,
    lastName: item.last_name,
    lifecycle: toContactLifecycle(item.lifecycle_status),
    source: toContactSource(item.source_type),
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  };
}

export default async function ContactsPage() {
  const response = await serverJson<ContactsListApiResponse>(
    ENDPOINTS.contacts.list,
  );
  const contacts = response.items.map(toContactListItem);

  return (
    <div className="page-stack">
      <PageIntro
        title="Contacts"
        description="Browse, filter, and manage contacts. Select rows to bulk unsubscribe or update list membership."
        actions={
          <div className="flex gap-3">
            <Button asChild variant="outline">
              <Link href="/contacts/import">Import CSV</Link>
            </Button>
            <Button asChild>
              <Link href="/contacts/new">Add contact</Link>
            </Button>
          </div>
        }
      />
      <ContactsTable contacts={contacts} lists={lists} />
    </div>
  );
}
