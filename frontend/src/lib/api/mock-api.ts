import { getDomainDetail, domainList } from "@/app/(dashboard)/domains/_lib/domains-queries";
import {
  getMockProvisioningAttempt,
  getMockProvisioningAudit,
  getMockZones,
} from "@/app/(dashboard)/domains/_lib/provisioning-queries";
import {
  getPostmasterData,
  getWarmupStatus,
} from "@/app/(dashboard)/domains/_lib/warmup-queries";
import {
  getBreakerMatrix,
  getBreakerTimeline,
  getQueueSnapshot,
} from "@/app/(dashboard)/ops/_lib/ops-queries";
import {
  getDomainReputationData,
  getEngagementTimeSeries,
  getOpenRateHeatmap,
  getTopCampaigns,
} from "@/app/(dashboard)/analytics/_lib/analytics-queries";
import { contactList } from "@/app/(dashboard)/contacts/_lib/contacts-queries";
import { lists } from "@/app/(dashboard)/lists/_lib/lists-queries";
import { mockSegments } from "@/app/(dashboard)/segments/_lib/segments-queries";
import { senderProfiles } from "@/app/(dashboard)/sender-profiles/_lib/sender-profiles-queries";
import {
  mockMergeTags,
  mockTemplates,
  getTemplateById,
  getVersionsForTemplate,
} from "@/app/(dashboard)/templates/_lib/templates-queries";
import {
  campaigns,
  getCampaignById,
  getMockCampaignDetail,
  getMockMessagesPage,
} from "@/app/(dashboard)/campaigns/_lib/campaigns-queries";
import { mockSuppressionList } from "@/app/(dashboard)/suppression/_lib/suppression-queries";
import { toApiError } from "@/lib/api/errors";
import type { DomainStatus, ProvisioningProvider } from "@/types/domain";

type QueryValue = string | number | boolean | null | undefined;

const notFoundPayload = { detail: "Mock API resource not found." };

function notFound(path: string): never {
  throw toApiError(404, notFoundPayload, {
    method: "GET",
    path,
    requestId: "mock-api",
  });
}

function domainVerificationStatus(status: DomainStatus) {
  if (status === "verified") return "verified";
  if (status === "pending") return "pending";
  return "verifying";
}

function domainReputationStatus(status: DomainStatus) {
  if (status === "cooling" || status === "burnt" || status === "retired") {
    return status;
  }
  return "healthy";
}

function toApiDomainListItem(item: (typeof domainList)[number]) {
  return {
    id: item.id,
    name: item.name,
    verification_status: domainVerificationStatus(item.status),
    reputation_status: domainReputationStatus(item.status),
    breaker_state: item.breaker,
    updated_at: item.updatedAt,
  };
}

function toApiDomainDetail(domainId: string) {
  const detail = getDomainDetail(domainId);
  const attempt = getMockProvisioningAttempt(domainId);

  if (!detail && !attempt) {
    return notFound(`/domains/${domainId}`);
  }

  const status = detail?.status ?? (attempt?.status === "completed" ? "verified" : "verifying");

  return {
    id: detail?.id ?? domainId,
    name: detail?.name ?? attempt?.domainName ?? domainId,
    dns_provider: attempt?.provider ?? "manual",
    breaker_state: detail?.breaker ?? "closed",
    verification_status: domainVerificationStatus(status),
    reputation_status: domainReputationStatus(status),
    created_at: detail?.createdAt ?? attempt?.startedAt ?? new Date().toISOString(),
    updated_at:
      detail?.updatedAt ??
      attempt?.completedAt ??
      attempt?.startedAt ??
      new Date().toISOString(),
    dns_records:
      detail?.dnsRecords.map((record) => ({
        id: record.id,
        record_type: record.type,
        name: record.hostname,
        value: record.value,
        purpose: record.purpose,
        verification_status:
          record.status === "valid"
            ? "verified"
            : record.status === "invalid"
              ? "failed"
              : "pending",
        last_verified_at: record.lastCheckedAt,
      })) ?? [],
  };
}

function toApiWarmup(domainId: string) {
  const warmup = getWarmupStatus(domainId);
  if (!warmup) {
    return notFound(`/domains/${domainId}/warmup`);
  }

  return {
    domain_id: warmup.domainId,
    lifecycle: warmup.lifecycle,
    current_day: warmup.currentDay,
    total_days: warmup.totalDays,
    today_cap: warmup.todayCap,
    today_sends: warmup.todaySends,
    scheduled_graduation_at: warmup.scheduledGraduationAt,
    graduated_at: warmup.graduatedAt,
    schedule: {
      preset: warmup.schedule.preset,
      total_days: warmup.schedule.totalDays,
      days: warmup.schedule.days.map((day) => ({
        day: day.day,
        cap: day.cap,
        actual_sends: day.actualSends,
      })),
    },
  };
}

function toApiPostmaster(domainId: string) {
  const postmaster = getPostmasterData(domainId);

  return {
    connected: postmaster.connected,
    as_of: postmaster.asOf,
    metrics: postmaster.metrics.map((metric) => ({
      date: metric.date,
      spam_rate_pct: metric.spamRatePct,
      domain_reputation: metric.domainReputation,
      spf_pass_pct: metric.spfPassPct,
      dkim_pass_pct: metric.dkimPassPct,
      dmarc_pass_pct: metric.dmarcPassPct,
    })),
  };
}

function toApiProvisioningStatus(domainId: string) {
  const attempt = getMockProvisioningAttempt(domainId);
  if (!attempt) {
    return {
      domain_id: domainId,
      status: "not_started",
      steps: [],
    };
  }

  return {
    domain_id: attempt.domainId,
    run_id: attempt.id,
    status: attempt.status,
    reason_code: attempt.failureReason,
    started_at: attempt.startedAt,
    completed_at: attempt.completedAt,
    steps: attempt.steps.map((step) => ({
      name: step.key,
      status: step.status,
      at: step.completedAt ?? step.startedAt ?? undefined,
      message: step.errorDetail,
    })),
  };
}

function toApiProvisioningAttempt(attempt: ReturnType<typeof getMockProvisioningAudit>[number]) {
  return {
    id: attempt.id,
    domain_id: attempt.domainId,
    domain_name: attempt.domainName,
    provider: attempt.provider,
    status: attempt.status,
    started_at: attempt.startedAt,
    completed_at: attempt.completedAt,
    failure_reason: attempt.failureReason,
    failure_remediation: attempt.failureRemediation,
    steps: attempt.steps.map((step) => ({
      name: step.key,
      status: step.status,
      at: step.completedAt ?? step.startedAt ?? undefined,
      message: step.errorDetail,
    })),
  };
}

function toApiBreaker(entry: ReturnType<typeof getBreakerMatrix>[number]) {
  return {
    id: entry.id,
    scope: entry.scope,
    entity_id: entry.entityId,
    entity_name: entry.entityName,
    state: entry.state,
    tripped_at: entry.trippedAt,
    reason: entry.reason,
    bounce_rate_pct: entry.bounceRatePct,
    complaint_rate_pct: entry.complaintRatePct,
    auto_reset_at: entry.autoResetAt,
    updated_at: entry.updatedAt,
  };
}

function toApiQueue(row: ReturnType<typeof getQueueSnapshot>[number]) {
  return {
    domain_id: row.domainId,
    domain_name: row.domainName,
    queue_name: row.queueName,
    worker_count: row.workerCount,
    queue_depth: row.queueDepth,
    oldest_queued_age_seconds: row.oldestQueuedAgeSeconds,
    denials_per_minute: row.denialsPerMinute,
    updated_at: row.updatedAt,
  };
}

function toApiSenderProfile(profile: (typeof senderProfiles)[number]) {
  return {
    id: profile.id,
    display_name: profile.name,
    from_name: profile.fromName,
    from_email: profile.fromEmail,
    reply_to: profile.replyTo,
    domain_id: profile.domainId,
    ip_pool_id: profile.ipPool,
    is_active: profile.status === "active",
    created_at: profile.createdAt,
    updated_at: profile.updatedAt,
  };
}

function toApiContact(contact: (typeof contactList)[number]) {
  return {
    id: contact.id,
    email: contact.email,
    first_name: contact.firstName,
    last_name: contact.lastName,
    lifecycle_status: contact.lifecycle,
    source_type: contact.source,
    created_at: contact.createdAt,
    updated_at: contact.updatedAt,
  };
}

function toApiList(list: (typeof lists)[number]) {
  return {
    id: list.id,
    name: list.name,
    description: list.description,
    member_count: list.memberCount,
    created_at: list.createdAt,
  };
}

function toApiSegment(segment: (typeof mockSegments)[number]) {
  return {
    id: segment.id,
    name: segment.name,
    description: segment.description,
    dsl_json: segment.dslJson,
    last_computed_count: segment.lastComputedCount,
    last_computed_at: segment.lastComputedAt,
    created_at: segment.createdAt,
    updated_at: segment.updatedAt,
  };
}

function toApiTemplate(template: (typeof mockTemplates)[number]) {
  return {
    id: template.id,
    name: template.name,
    description: template.description,
    head_version_number: template.activeVersion,
    created_at: template.createdAt,
    updated_at: template.updatedAt,
    versions: getVersionsForTemplate(template.id).map((version) => ({
      id: version.id,
      template_id: version.templateId,
      version_number: version.version,
      subject: version.subject,
      body_text: version.bodyText,
      body_html: version.bodyHtml,
      is_published: version.publishedAt !== null,
      created_at: version.createdAt,
    })),
  };
}

function toApiSuppression(entry: (typeof mockSuppressionList)[number]) {
  return {
    id: entry.id,
    email: entry.email,
    reason_code:
      entry.reason === "spam_complaint"
        ? "complaint"
        : entry.reason === "manual"
          ? "manual"
          : entry.reason,
    source: entry.source,
    first_suppressed_at: entry.createdAt,
    expires_at: null,
  };
}

function toApiCampaign(campaignId: string) {
  const campaign = getCampaignById(campaignId);
  return {
    id: campaign.id,
    name: campaign.name,
    status: campaign.status,
    updated_at: campaign.updatedAt,
  };
}

function toApiMessagesPage(
  campaignId: string,
  cursor: string | null,
  status: string | null,
  limit: number,
) {
  const page = getMockMessagesPage(campaignId, cursor, status, limit);

  return {
    items: page.messages.map((message) => ({
      message_id: message.id,
      id: message.id,
      campaign_id: message.campaignId,
      to_email: message.email,
      email: message.email,
      recipient_email: message.email,
      status: message.status,
      last_event_at: message.lastEventAt,
      has_bounce: message.hasBounce,
      has_click: message.hasClick,
      has_complaint: message.hasComplaint,
      ses_message_id: message.sesMessageId,
    })),
    next_cursor: page.nextCursor,
  };
}

function providerFromSearch(value: string | null): Exclude<ProvisioningProvider, "manual"> {
  return value === "route53" ? "route53" : "cloudflare";
}

function numberFromSearch(value: string | null, fallback: number) {
  if (!value) return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function getMockApiJson(
  url: URL,
  query?: Record<string, QueryValue>,
): unknown | undefined {
  const path = url.pathname;
  const params = new URLSearchParams(url.searchParams);

  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }

  if (path === "/domains") {
    return { items: domainList.map(toApiDomainListItem) };
  }

  if (path === "/domains/zones") {
    const provider = providerFromSearch(params.get("provider"));
    return { items: getMockZones(provider) };
  }

  const domainMatch = /^\/domains\/([^/]+)$/.exec(path);
  if (domainMatch) {
    return toApiDomainDetail(decodeURIComponent(domainMatch[1]!));
  }

  const warmupMatch = /^\/domains\/([^/]+)\/warmup$/.exec(path);
  if (warmupMatch) {
    return toApiWarmup(decodeURIComponent(warmupMatch[1]!));
  }

  const postmasterMatch = /^\/domains\/([^/]+)\/postmaster$/.exec(path);
  if (postmasterMatch) {
    return toApiPostmaster(decodeURIComponent(postmasterMatch[1]!));
  }

  const provisioningStatusMatch = /^\/domains\/([^/]+)\/provisioning-status$/.exec(path);
  if (provisioningStatusMatch) {
    return toApiProvisioningStatus(decodeURIComponent(provisioningStatusMatch[1]!));
  }

  if (path === "/ops/provisioning") {
    return { items: getMockProvisioningAudit().map(toApiProvisioningAttempt) };
  }

  if (path === "/ops/queues") {
    return { items: getQueueSnapshot().map(toApiQueue) };
  }

  if (path === "/circuit-breakers") {
    return { items: getBreakerMatrix().map(toApiBreaker) };
  }

  const breakerTimelineMatch = /^\/circuit-breakers\/([^/]+)\/timeline$/.exec(path);
  if (breakerTimelineMatch) {
    return { items: getBreakerTimeline(decodeURIComponent(breakerTimelineMatch[1]!)) };
  }

  if (path === "/analytics/overview") {
    return {
      sends_today: 18_240,
      sends_7d: 98_412,
      bounce_rate: 0.42,
      complaint_rate: 0.01,
      open_rate: 37.8,
      click_rate: 6.3,
      last_updated_at: "2026-04-23T11:58:00Z",
      top_campaigns: getTopCampaigns().map((campaign) => ({
        campaign_id: campaign.id,
        name: campaign.name,
        sends_today: campaign.sends,
        delivered: Math.round(campaign.sends * 0.985),
        open_rate: campaign.openRate,
        sparkline: campaign.sparkline,
      })),
      time_series: getEngagementTimeSeries(),
      open_rate_heatmap: getOpenRateHeatmap(),
    };
  }

  if (path === "/analytics/reputation") {
    return {
      last_updated_at: "2026-04-23T11:58:00Z",
      items: getDomainReputationData().map((domain) => ({
        id: domain.id,
        name: domain.name,
        bounceRate: domain.bounceRate,
        complaintRate: domain.complaintRate,
        deliveryRate: domain.deliveryRate,
        breakerState: domain.breakerState,
        warmupStage: domain.warmupStage,
        riskLevel: domain.riskLevel,
      })),
    };
  }

  if (path === "/contacts") {
    return { items: contactList.map(toApiContact) };
  }

  if (path === "/lists") {
    return { items: lists.map(toApiList) };
  }

  if (path === "/sender-profiles") {
    return { items: senderProfiles.map(toApiSenderProfile) };
  }

  if (path === "/segments") {
    return { items: mockSegments.map(toApiSegment) };
  }

  const segmentMatch = /^\/segments\/([^/]+)$/.exec(path);
  if (segmentMatch) {
    const segment = mockSegments.find((item) => item.id === decodeURIComponent(segmentMatch[1]!));
    return segment ? toApiSegment(segment) : notFound(path);
  }

  if (path === "/templates") {
    return { items: mockTemplates.map(toApiTemplate) };
  }

  if (path === "/templates/merge-tags") {
    return mockMergeTags;
  }

  const templateMatch = /^\/templates\/([^/]+)$/.exec(path);
  if (templateMatch) {
    const template = getTemplateById(decodeURIComponent(templateMatch[1]!));
    return template ? toApiTemplate(template) : notFound(path);
  }

  if (path === "/suppression") {
    return {
      items: mockSuppressionList.map(toApiSuppression),
      total: mockSuppressionList.length,
      limit: numberFromSearch(params.get("limit"), 200),
      offset: numberFromSearch(params.get("offset"), 0),
    };
  }

  const campaignMatch = /^\/campaigns\/([^/]+)$/.exec(path);
  if (campaignMatch) {
    const campaignId = decodeURIComponent(campaignMatch[1]!);
    if (!campaigns.some((campaign) => campaign.id === campaignId)) {
      return notFound(path);
    }
    return toApiCampaign(campaignId);
  }

  const messagesMatch = /^\/campaigns\/([^/]+)\/messages$/.exec(path);
  if (messagesMatch) {
    return toApiMessagesPage(
      decodeURIComponent(messagesMatch[1]!),
      params.get("cursor"),
      params.get("status"),
      numberFromSearch(params.get("limit"), 20),
    );
  }

  const campaignPreflightMatch = /^\/campaigns\/([^/]+)\/preflight$/.exec(path);
  if (campaignPreflightMatch) {
    const detail = getMockCampaignDetail(decodeURIComponent(campaignPreflightMatch[1]!));
    return {
      checks: [],
      audience_count: detail.kpis.queued + detail.kpis.sent,
    };
  }

  return undefined;
}
