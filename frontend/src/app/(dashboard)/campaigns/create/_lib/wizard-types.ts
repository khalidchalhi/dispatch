import type { SenderProfile } from "@/types/domain";
import type { List } from "@/types/list";
import type { Segment } from "@/types/segment";
import type { Template, TemplateVersion } from "@/types/template";

export type WizardTemplate = Template & {
  versions: TemplateVersion[];
};

export type WizardData = {
  senderProfiles: SenderProfile[];
  templates: WizardTemplate[];
  segments: Segment[];
  lists: List[];
};
