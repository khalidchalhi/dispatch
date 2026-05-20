# Beginner AWS, Cloudflare, and Domain Setup for Dispatch

Date: 2026-05-20

This is a fresh beginner-first setup guide for getting Dispatch ready to send real email through AWS SES with DNS managed in Cloudflare.

It intentionally does not assume you know the AWS console, Cloudflare, DNS, SES, ECS, RDS, Redis, or email authentication. Follow it slowly. Email infrastructure punishes rushed setup.

## What You Are Building

Dispatch needs three layers to run for real:

1. Domains and DNS in Cloudflare.
2. AWS infrastructure for the app, database, Redis, workers, logs, secrets, and SES.
3. Email-specific setup for SES identities, DKIM, SPF, DMARC, MAIL FROM, suppression, event webhooks, and warmup.

The safest order is:

1. Buy domains.
2. Put domains in Cloudflare.
3. Create and secure AWS account.
4. Verify sending domains in SES.
5. Request SES production access.
6. Create AWS app infrastructure.
7. Deploy Dispatch.
8. Run migrations.
9. Test with tiny sends.
10. Warm up slowly.

## Beginner Glossary

### Domain

A domain is the name you buy, like `example.com`.

### Subdomain

A subdomain is a name under a domain, like `app.example.com`, `api.example.com`, `bounce.example.com`, or `track.example.com`. You usually do not buy subdomains. You create them with DNS records.

### DNS

DNS is the public phonebook for your domain. Cloudflare will hold records that say things like:

- `app.example.com` goes to the Dispatch web app.
- `api.example.com` goes to the Dispatch API.
- SES is allowed to send email for `example.com`.
- DKIM keys prove emails are really from your domain.

### AWS Region

AWS has regions like `us-east-1`, `us-west-2`, `eu-west-1`, etc. SES sandbox and production access are region-specific, so pick one first region and stick to it.

Suggested first region:

- `eu-west-1` if you want Europe/Ireland.
- `us-east-1` if you want the most common AWS default.

Use the same region in Dispatch config as `AWS_REGION`.

### SES

Amazon Simple Email Service. Dispatch uses it as the only sending provider.

### DKIM

DKIM is an email signature. SES gives you DNS records. You put them in Cloudflare. Mailbox providers use them to trust your email.

### SPF

SPF says which servers are allowed to send mail for a domain or MAIL FROM subdomain.

### DMARC

DMARC tells mailbox providers what to do if SPF/DKIM fail. Start with monitoring mode, then tighten later.

### MAIL FROM / Return-Path

This is the hidden bounce domain. For SES, use a dedicated subdomain like `bounce.example.com`.

### SNS

Amazon Simple Notification Service. SES sends bounce, complaint, delivery, open, and click events into SNS. SNS then calls your Dispatch webhook.

## Official Docs Used

Use these as the official reference if the AWS or Cloudflare UI changes:

- AWS SES domain identities and DKIM: https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html
- AWS SES production access / sandbox: https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html
- AWS SES custom MAIL FROM: https://docs.aws.amazon.com/ses/latest/dg/mail-from.html
- AWS SES SNS event destinations: https://docs.aws.amazon.com/ses/latest/dg/event-publishing-add-event-destination-sns.html
- AWS SES account-level suppression list: https://docs.aws.amazon.com/ses/latest/dg/sending-email-suppression-list.html
- AWS SES custom open/click tracking domains: https://docs.aws.amazon.com/ses/latest/dg/configure-custom-open-click-domains.html
- Cloudflare add domain and nameservers: https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/
- Cloudflare proxy status and DNS-only records: https://developers.cloudflare.com/learning-paths/get-started/domain-resolution/proxy-status/
- Cloudflare API tokens: https://developers.cloudflare.com/fundamentals/api/get-started/create-token/
- AWS RDS PostgreSQL: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_GettingStarted.CreatingConnecting.PostgreSQL.html
- AWS ElastiCache Redis/Valkey: https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Clusters.Create.html
- AWS ECS Fargate: https://docs.aws.amazon.com/AmazonECS/latest/userguide/getting-started-fargate.html
- AWS Secrets Manager: https://docs.aws.amazon.com/secretsmanager/latest/userguide/create_secret.html

## Domain Buying Plan

### Minimum Setup

For the absolute minimum, buy one real brand domain:

```text
yourbrand.com
```

Then create subdomains:

```text
app.yourbrand.com
api.yourbrand.com
unsubscribe.yourbrand.com
bounce.yourbrand.com
track.yourbrand.com
mail.yourbrand.com
```

This is enough for early testing and low volume.

### Recommended Dispatch Setup

For a serious marketing/cashflow tool, use one primary business domain and a small pool of dedicated sending domains.

Buy:

```text
yourbrand.com                 primary company/app domain
yourbrandmail.com             dedicated sending domain 1
yourbrandupdates.com          dedicated sending domain 2
getyourbrand.com              optional sending domain 3
```

Use:

```text
app.yourbrand.com             Dispatch frontend
api.yourbrand.com             Dispatch backend API and SES webhook
unsubscribe.yourbrand.com     public unsubscribe/preferences page

hello@yourbrandmail.com       sender profile 1
updates@yourbrandupdates.com  sender profile 2
team@getyourbrand.com         sender profile 3

bounce.yourbrandmail.com      SES custom MAIL FROM for domain 1
track.yourbrandmail.com       SES open/click tracking for domain 1

bounce.yourbrandupdates.com   SES custom MAIL FROM for domain 2
track.yourbrandupdates.com    SES open/click tracking for domain 2
```

### What Not To Buy

Do not buy 50 cheap random domains. Do not buy spammy TLDs just because they are cheap. Avoid:

```text
.xyz
.top
.click
.work
.buzz
typo domains
lookalike domains
domains unrelated to the brand
```

Good email reputation comes from consistent identity, consent, low bounce rate, low complaint rate, and slow warmup. Lots of random domains looks suspicious.

### Best TLD Choices

Prefer:

```text
.com
.net
.co
country TLD if it matches the business
```

For marketing email, `.com` is usually the safest beginner choice.

## Cloudflare Setup

### Step 1 - Create a Cloudflare Account

1. Go to https://dash.cloudflare.com.
2. Create an account.
3. Enable two-factor authentication.
4. Save backup codes somewhere safe.

### Step 2 - Buy Domains

Simplest beginner path:

1. Buy the domains directly in Cloudflare Registrar.
2. Cloudflare will automatically be the DNS provider.

If you already bought domains elsewhere:

1. Add each domain to Cloudflare.
2. Cloudflare gives you two nameservers.
3. Go to your registrar.
4. Replace the registrar nameservers with the Cloudflare nameservers.
5. Wait until Cloudflare says the zone is active.

### Step 3 - Add Each Domain to Cloudflare

For each domain:

1. Cloudflare dashboard.
2. Go to `Websites` or `Domains`.
3. Click `Add a site` or `Onboard a domain`.
4. Enter only the apex domain:

```text
yourbrand.com
yourbrandmail.com
yourbrandupdates.com
```

Do not enter:

```text
www.yourbrand.com
app.yourbrand.com
```

Those are subdomains. Add only the root/apex domain.

### Step 4 - Understand Cloudflare Proxy

Cloudflare has two modes for A/AAAA/CNAME records:

```text
Proxied     orange cloud, HTTP traffic goes through Cloudflare
DNS only    gray cloud, DNS resolves directly
```

Use `Proxied` for:

```text
app.yourbrand.com
api.yourbrand.com
www.yourbrand.com
```

Use `DNS only` for:

```text
SES DKIM CNAME records
SES verification records
SES tracking CNAME records unless intentionally putting Cloudflare in front
ACM certificate validation CNAME records
```

TXT and MX records are always DNS-only.

### Step 5 - Create a Cloudflare API Token

Dispatch domain provisioning needs permission to create DNS records.

In Cloudflare:

1. Click your profile icon.
2. Go to `My Profile`.
3. Go to `API Tokens`.
4. Click `Create Token`.
5. Use a custom token.
6. Permissions:

```text
Zone - Zone - Read
Zone - DNS - Edit
```

7. Scope:

```text
Include - Specific zone - yourbrand.com
Include - Specific zone - yourbrandmail.com
Include - Specific zone - yourbrandupdates.com
```

8. Create token.
9. Copy it once.
10. Store it in AWS Secrets Manager and local `.env`.

Do not use the Global API Key unless there is no other option.

## AWS Setup Overview

You will need these AWS services:

| AWS Service | What Dispatch Uses It For |
|---|---|
| IAM / Identity Center | Users, permissions, roles |
| Billing / Budgets | Cost alerts |
| SES | Sending email |
| SNS | SES event notifications |
| RDS PostgreSQL | Main database |
| ElastiCache Redis or Valkey | Celery broker, rate limits, cache |
| ECS Fargate | Run API, frontend, workers, webhook, scheduler |
| ECR | Store Docker images |
| ALB | Public HTTPS load balancer |
| ACM | TLS certificates |
| Secrets Manager | Store secrets safely |
| CloudWatch | Logs and alarms |
| S3 | CSV import storage and future bulk files |
| VPC | Private network around AWS services |

## AWS Account Safety First

### Step 1 - Create AWS Account

1. Go to https://aws.amazon.com.
2. Create an account.
3. Use a real email you control.
4. Add billing details.
5. Choose a support plan. Basic is fine at first.

### Step 2 - Secure the Root User

The root user is the master key to the whole AWS account.

Do this immediately:

1. Sign in as root.
2. Enable MFA.
3. Save recovery codes.
4. Do not use root for daily work.

### Step 3 - Create an Admin User

Beginner path:

1. Open AWS console.
2. Search for `IAM Identity Center`.
3. Enable it.
4. Create your user.
5. Give yourself administrator access.
6. Sign out of root.
7. Sign in with the new admin user.

### Step 4 - Create a Budget Alert

1. Search AWS for `Budgets`.
2. Create a monthly cost budget.
3. Start with something like:

```text
$25 or $50 while learning
```

4. Add email alerts at:

```text
50 percent
80 percent
100 percent
```

## Pick Your AWS Region

Pick one first region for SES and the app.

Recommended:

```text
eu-west-1
```

or:

```text
us-east-1
```

Important:

- SES sandbox status is per region.
- SES production access is per region.
- MAIL FROM records include the region.
- Tracking domains must match the region.
- Your app config must use the same region.

Set:

```text
AWS_REGION=eu-west-1
```

or:

```text
AWS_REGION=us-east-1
```

## SES Setup

### Step 1 - Open SES

1. Sign in to AWS console.
2. Top-right region selector: choose your region.
3. Search for `SES`.
4. Open `Amazon Simple Email Service`.

### Step 2 - Understand Sandbox Mode

New SES accounts start in sandbox mode.

In sandbox mode:

- You can only send to verified email addresses/domains or the SES mailbox simulator.
- The default limit is low.
- You cannot send real marketing campaigns yet.

This is normal.

### Step 3 - Create a Configuration Set

Configuration sets attach tracking and event publishing to messages.

Create one:

1. SES console.
2. Left menu: `Configuration sets`.
3. Click `Create set`.
4. Name:

```text
dispatch-default
```

5. Keep sending enabled.
6. Save.

Later, Dispatch should send with this configuration set.

### Step 4 - Verify a Sending Domain

For each sending domain:

```text
yourbrandmail.com
yourbrandupdates.com
getyourbrand.com
```

Do:

1. SES console.
2. Left menu: `Verified identities`.
3. Click `Create identity`.
4. Choose `Domain`.
5. Enter:

```text
yourbrandmail.com
```

6. Enable Easy DKIM.
7. Choose DKIM length 2048 if available.
8. Assign default configuration set:

```text
dispatch-default
```

9. Create identity.
10. SES shows DKIM CNAME records.
11. Copy each CNAME into Cloudflare DNS.

In Cloudflare:

- Type: `CNAME`
- Name: value SES gives you
- Target: value SES gives you
- Proxy: `DNS only`

Wait until SES shows the identity as verified.

### Step 5 - Add Custom MAIL FROM

For each SES verified domain, use a bounce subdomain:

```text
bounce.yourbrandmail.com
```

In SES:

1. Go to `Verified identities`.
2. Click the domain.
3. Find `Custom MAIL FROM domain`.
4. Click `Edit`.
5. Enable custom MAIL FROM.
6. Enter:

```text
bounce.yourbrandmail.com
```

7. Behavior on MX failure:

```text
Reject message
```

This matches Dispatch's fail-closed posture.

SES gives you two records.

In Cloudflare, add:

```text
Type: MX
Name: bounce
Priority: 10
Target: feedback-smtp.<aws-region>.amazonses.com
```

and:

```text
Type: TXT
Name: bounce
Value: v=spf1 include:amazonses.com ~all
```

Important:

- The MAIL FROM subdomain must have exactly one MX record.
- Do not use `bounce` for any other email service.

### Step 6 - Add DMARC

Start with monitoring mode.

In Cloudflare for each sending domain:

```text
Type: TXT
Name: _dmarc
Value: v=DMARC1; p=none; rua=mailto:dmarc@yourbrand.com; adkim=s; aspf=s; pct=100
```

Later, after warmup and monitoring:

```text
p=quarantine
```

Eventually, when everything is stable:

```text
p=reject
```

Do not start at `p=reject` while learning.

### Step 7 - Add SPF for Visible Sending Domain If Needed

If you send directly from:

```text
hello@yourbrandmail.com
```

and SES asks for SPF at the domain level, add:

```text
Type: TXT
Name: @
Value: v=spf1 include:amazonses.com ~all
```

Important:

- A hostname can only have one SPF TXT record.
- If another email provider already uses SPF on the same domain, merge them into one record.

Example merged SPF:

```text
v=spf1 include:amazonses.com include:_spf.google.com ~all
```

Do not create two separate SPF records for the same hostname.

### Step 8 - Enable Account-Level Suppression

In SES:

1. Left menu: `Suppression list`.
2. Account-level settings.
3. Enable suppression list.
4. Enable reasons:

```text
BOUNCE
COMPLAINT
```

This helps protect reputation.

### Step 9 - Create SNS Topics for SES Events

Dispatch needs SES events to update bounces, complaints, deliveries, opens, clicks, and suppression.

Create SNS topics:

```text
dispatch-ses-bounces
dispatch-ses-complaints
dispatch-ses-deliveries
dispatch-ses-opens
dispatch-ses-clicks
dispatch-ses-rendering-failures
```

Beginner simpler option:

```text
dispatch-ses-events
```

One topic is easier. Multiple topics are cleaner later.

In AWS:

1. Search `SNS`.
2. Go to `Topics`.
3. Create topic.
4. Type: Standard.
5. Name it.

### Step 10 - Subscribe Dispatch Webhook to SNS

Your production webhook URL should look like:

```text
https://api.yourbrand.com/webhooks/ses
```

or whatever route the backend exposes for SES SNS.

In SNS:

1. Open the topic.
2. Click `Create subscription`.
3. Protocol:

```text
HTTPS
```

4. Endpoint:

```text
https://api.yourbrand.com/webhooks/ses
```

5. Save.
6. SNS sends a confirmation request.
7. Dispatch webhook must confirm it.

If Dispatch does not auto-confirm yet, this needs code/support before production.

### Step 11 - Attach SNS Event Destination to SES Configuration Set

In SES:

1. Go to `Configuration sets`.
2. Open `dispatch-default`.
3. Go to `Event destinations`.
4. Add destination.
5. Destination type: SNS.
6. Select the SNS topic.
7. Enable event types:

```text
Send
Reject
Bounce
Complaint
Delivery
Open
Click
Rendering failure
Delivery delay
Subscription
```

For the minimum, use:

```text
Bounce
Complaint
Delivery
Open
Click
```

### Step 12 - Custom Tracking Domain

SES can rewrite open/click tracking links to use your own domain instead of an Amazon-looking domain.

Use:

```text
track.yourbrandmail.com
```

For basic HTTP tracking:

1. Verify `track.yourbrandmail.com` as an SES identity.
2. Add SES tracking CNAME in Cloudflare.
3. Set it as tracking domain in the configuration set.

For HTTPS tracking:

1. Create `track.yourbrandmail.com`.
2. Use CloudFront as the CDN in front of the SES regional tracking domain.
3. Add ACM certificate for `track.yourbrandmail.com`.
4. Add Cloudflare DNS CNAME from `track` to the CloudFront distribution.
5. In SES configuration set, set tracking domain and `HttpsPolicy=REQUIRE`.

Beginner recommendation:

- Do this after basic SES sending works.
- Use the default SES tracking domain at first if you are still learning.
- Add custom HTTPS tracking before serious marketing sends.

## Request SES Production Access

Do this after at least one domain is verified with DKIM.

In SES:

1. Go to `Account dashboard`.
2. Look for the sandbox warning.
3. Click `Request production access`.
4. Choose the mail type honestly:

```text
Marketing
```

if this platform sends campaigns.

5. Website URL:

```text
https://yourbrand.com
```

6. Additional contacts: your email.
7. Explain:

```text
We operate an internal email platform for opted-in contacts only. We verify sending domains with DKIM, SPF, DMARC, and custom MAIL FROM. We process bounces and complaints through SES event webhooks, maintain account-level and application-level suppression lists, include unsubscribe links in marketing email, and warm up domains gradually with per-domain throttles and circuit breakers.
```

8. Include expected starting volume:

```text
Initial: under 1,000/day while testing
Warmup: gradual increase per domain
Target: only after reputation is stable
```

9. Submit.

AWS may ask questions. Answer honestly and specifically.

Do not say "cold email" or "scraped lists". Do not use purchased lists. That will hurt approval and sender reputation.

## AWS Infrastructure Setup

You can create this manually first, then later move it into Terraform.

### VPC

Beginner path:

1. Search `VPC`.
2. Use the default VPC at first only for learning.
3. For production, create a dedicated VPC with:

```text
2 public subnets
2 private subnets
NAT gateway
internet gateway
security groups
```

Public:

- Load balancer.

Private:

- ECS tasks.
- RDS.
- Redis.

### RDS PostgreSQL

Dispatch needs PostgreSQL 15+.

In AWS:

1. Search `RDS`.
2. Click `Create database`.
3. Choose:

```text
Standard create
PostgreSQL
Version 15 or newer
```

4. Template:

```text
Dev/Test for early setup
Production later
```

5. DB instance identifier:

```text
dispatch-postgres
```

6. Database name:

```text
dispatch
```

7. Master username:

```text
dispatch_app
```

8. Password: generate strong password and store in Secrets Manager.
9. Public access:

```text
No
```

10. Security group:

Allow PostgreSQL port:

```text
5432
```

only from ECS tasks or your temporary admin/bastion access.

### ElastiCache Redis or Valkey

Dispatch uses Redis for Celery, token buckets, caches, and idempotency helpers.

In AWS:

1. Search `ElastiCache`.
2. Create cache.
3. Engine:

```text
Redis OSS or Valkey
```

4. Name:

```text
dispatch-redis
```

5. Use private subnets.
6. Security group:

Allow Redis port:

```text
6379
```

only from ECS tasks.

### S3

Create a private bucket for imports and generated files:

```text
dispatch-imports-prod
```

Settings:

- Block all public access: enabled.
- Versioning: optional but recommended.
- Encryption: enabled.

This will replace local file storage for production CSV imports.

### Secrets Manager

Create secrets for:

```text
dispatch/DATABASE_URL
dispatch/REDIS_URL
dispatch/SECRET_KEY
dispatch/JWT_SECRET
dispatch/CLOUDFLARE_API_TOKEN
dispatch/CLOUDFLARE_ACCOUNT_ID
dispatch/SESSION_SECRET
dispatch/WEBHOOK_SIGNING_SECRET
dispatch/GOOGLE_POSTMASTER_CLIENT_ID       later
dispatch/GOOGLE_POSTMASTER_CLIENT_SECRET   later
```

Do not store secrets directly in GitHub or plain config files.

### ECR

ECR stores Docker images.

Create repositories:

```text
dispatch-api
dispatch-web
dispatch-workers
dispatch-webhook
dispatch-scheduler
```

### ECS Fargate

Create one cluster:

```text
dispatch-prod
```

Create services:

```text
dispatch-api
dispatch-web
dispatch-worker-send
dispatch-worker-events
dispatch-worker-import
dispatch-worker-metrics
dispatch-scheduler
```

Each service needs:

- Task definition.
- Container image from ECR.
- Environment variables.
- Secrets from Secrets Manager.
- CloudWatch logs.
- IAM task role.
- Security group.

Only public services should be behind the load balancer:

```text
dispatch-web
dispatch-api
```

Workers should be private.

### Application Load Balancer

Create an ALB for:

```text
app.yourbrand.com
api.yourbrand.com
unsubscribe.yourbrand.com
```

Typical routing:

```text
app.yourbrand.com          -> frontend service
unsubscribe.yourbrand.com  -> frontend service
api.yourbrand.com          -> backend API service
api.yourbrand.com/webhooks/ses -> backend webhook route
```

Use HTTPS only.

### ACM Certificates

AWS Certificate Manager issues TLS certificates.

Create certificates for:

```text
app.yourbrand.com
api.yourbrand.com
unsubscribe.yourbrand.com
track.yourbrandmail.com       later if using CloudFront tracking
```

ACM gives DNS validation CNAME records.

Add those in Cloudflare as:

```text
Type: CNAME
Proxy: DNS only
```

### CloudWatch

Enable logs for:

```text
api
web
workers
webhook
scheduler
```

Create alarms for:

```text
API 5xx errors
ECS task restarts
RDS CPU/storage
Redis CPU/memory
SES bounce rate
SES complaint rate
DLQ depth if using queues
```

## DNS Record Templates

Replace `yourbrandmail.com` and `eu-west-1` with your real domain and AWS region.

### Main App Domain

```text
Type: CNAME
Name: app
Target: your-alb-or-cloudfront-target
Proxy: Proxied or DNS only
```

```text
Type: CNAME
Name: api
Target: your-alb-target
Proxy: Proxied or DNS only
```

```text
Type: CNAME
Name: unsubscribe
Target: your-frontend-target
Proxy: Proxied or DNS only
```

### SES DKIM Records

SES will give three CNAME records like:

```text
Type: CNAME
Name: abc123._domainkey
Target: abc123.dkim.amazonses.com
Proxy: DNS only
```

Add all three.

### Custom MAIL FROM

```text
Type: MX
Name: bounce
Priority: 10
Target: feedback-smtp.eu-west-1.amazonses.com
```

```text
Type: TXT
Name: bounce
Value: v=spf1 include:amazonses.com ~all
```

### DMARC

```text
Type: TXT
Name: _dmarc
Value: v=DMARC1; p=none; rua=mailto:dmarc@yourbrand.com; adkim=s; aspf=s; pct=100
```

### SPF

Only if needed on the visible sending domain:

```text
Type: TXT
Name: @
Value: v=spf1 include:amazonses.com ~all
```

### Tracking

HTTP beginner tracking:

```text
Type: CNAME
Name: track
Target: r.eu-west-1.awstrack.me
Proxy: DNS only
```

HTTPS tracking through CloudFront:

```text
Type: CNAME
Name: track
Target: your-cloudfront-distribution.cloudfront.net
Proxy: DNS only
```

## Dispatch Environment Variables

Exact names may differ by code config, but conceptually production needs:

```text
APP_ENV=production
AWS_REGION=eu-west-1

DATABASE_URL=postgresql+asyncpg://dispatch_app:<password>@<rds-endpoint>:5432/dispatch
REDIS_URL=redis://<elasticache-endpoint>:6379/0

SES_CONFIGURATION_SET=dispatch-default
SES_REGION=eu-west-1

CLOUDFLARE_API_TOKEN=<from-secrets-manager>
CLOUDFLARE_ACCOUNT_ID=<cloudflare-account-id>

SECRET_KEY=<strong-random>
JWT_SECRET=<strong-random>
SESSION_SECRET=<strong-random>
WEBHOOK_SIGNING_SECRET=<strong-random>

PUBLIC_APP_URL=https://app.yourbrand.com
PUBLIC_API_URL=https://api.yourbrand.com
PUBLIC_UNSUBSCRIBE_URL=https://unsubscribe.yourbrand.com
```

AWS credentials should come from ECS task roles in production, not long-lived access keys.

## IAM Roles and Permissions

Create ECS task roles with least privilege.

API/webhook tasks need:

```text
ses:SendEmail
ses:SendRawEmail
ses:GetEmailIdentity
ses:CreateEmailIdentity
ses:PutEmailIdentityDkimSigningAttributes
ses:PutEmailIdentityMailFromAttributes
ses:GetAccount
ses:ListSuppressedDestinations
ses:PutSuppressedDestination
ses:DeleteSuppressedDestination
sns:Publish
secretsmanager:GetSecretValue
s3:GetObject
s3:PutObject
s3:DeleteObject
```

Workers need:

```text
ses:SendEmail
ses:SendRawEmail
ses:GetAccount
secretsmanager:GetSecretValue
s3:GetObject
s3:PutObject
```

Domain provisioning tasks need:

```text
ses:CreateEmailIdentity
ses:GetEmailIdentity
ses:PutEmailIdentityMailFromAttributes
secretsmanager:GetSecretValue
```

Use Cloudflare API token for Cloudflare DNS instead of AWS IAM.

## Local to Production Setup Checklist

### Before Real Sending

- [ ] AWS account root MFA enabled.
- [ ] Admin user created.
- [ ] Billing budget created.
- [ ] Domains bought.
- [ ] Domains active in Cloudflare.
- [ ] Cloudflare API token created.
- [ ] AWS region chosen.
- [ ] SES domain identity verified.
- [ ] DKIM verified.
- [ ] Custom MAIL FROM verified.
- [ ] DMARC added with `p=none`.
- [ ] SES account-level suppression enabled.
- [ ] SES production access approved.
- [ ] SNS topics created.
- [ ] SES event destination created.
- [ ] Dispatch webhook reachable over HTTPS.
- [ ] RDS created.
- [ ] Redis/Valkey created.
- [ ] S3 private bucket created.
- [ ] Secrets stored in Secrets Manager.
- [ ] ECS services deployed.
- [ ] Migrations run against RDS.
- [ ] First test email sent to your own mailbox.
- [ ] Bounce/complaint webhook tested.
- [ ] Unsubscribe link tested.
- [ ] Suppression list tested.

### Before Marketing Work

- [ ] Full frontend e2e green for campaign, contacts, templates, suppression, unsubscribe, domains, analytics.
- [ ] Real backend and frontend running together.
- [ ] No mock fallback needed for production routes.
- [ ] Template editor and preview verified.
- [ ] Contact import verified.
- [ ] Segment builder verified.
- [ ] Unsubscribe public page verified.
- [ ] Suppressed contacts cannot be sent to.
- [ ] Warmup schedule active for every sending domain.
- [ ] Per-domain throttle working.
- [ ] Circuit breakers fail closed.
- [ ] SES production access approved.
- [ ] DNS records pass external checks.

### Before High Volume

- [ ] Send only to opted-in contacts.
- [ ] Start with tiny volumes.
- [ ] Watch bounce rate.
- [ ] Watch complaint rate.
- [ ] Watch delivery rate.
- [ ] Watch Gmail/Yahoo/Microsoft inbox placement.
- [ ] Increase volume gradually.
- [ ] Stop sending from any domain with bad signals.
- [ ] Move DMARC from `p=none` to `p=quarantine` only after confidence.
- [ ] Move DMARC to `p=reject` only after all legitimate sources are aligned.

## First Week Warmup Example

Use conservative numbers. New domains should not jump to high volume.

Example per sending domain:

```text
Day 1: 50
Day 2: 75
Day 3: 100
Day 4: 150
Day 5: 200
Day 6: 300
Day 7: 400
```

If bounces or complaints rise, do not increase. Hold or reduce.

## Common Beginner Mistakes

### Mistake: Buying Too Many Domains

More domains does not automatically mean more inboxing. Too many new domains can look suspicious.

### Mistake: Cloudflare Proxy on SES DKIM CNAME

SES verification CNAMEs should be DNS-only.

### Mistake: Two SPF Records

Never create two SPF TXT records for the same hostname. Merge them into one.

### Mistake: No MAIL FROM

Without custom MAIL FROM, alignment and bounce handling are weaker.

### Mistake: No Suppression

Suppressed or unsubscribed contacts must never receive email. This is a hard safety rule in Dispatch.

### Mistake: Requesting SES Production Before DNS Is Ready

Verify at least one real domain with DKIM before requesting production access.

### Mistake: Sending Marketing Without Unsubscribe

Marketing email needs a working unsubscribe path. Test it before any campaign.

### Mistake: Sending Before Webhooks Work

If SES bounce/complaint events do not reach Dispatch, the app cannot protect reputation properly.

## What To Give Codex Later

When you are ready to wire this into code/deployment, give Codex:

```text
AWS region:
Primary domain:
Sending domains:
Cloudflare account id:
RDS endpoint:
Redis endpoint:
S3 bucket name:
SES configuration set name:
SNS topic ARNs:
Public app URL:
Public API URL:
Public unsubscribe URL:
```

Do not paste raw secrets into chat unless you explicitly want them written into local env files. Prefer saying where they are stored in Secrets Manager.

## Suggested First Domain Setup

If you have not bought anything yet, start like this:

```text
Buy:
yourbrand.com
yourbrandmail.com
yourbrandupdates.com

Use:
app.yourbrand.com
api.yourbrand.com
unsubscribe.yourbrand.com

Send from:
hello@yourbrandmail.com
updates@yourbrandupdates.com

Bounce domains:
bounce.yourbrandmail.com
bounce.yourbrandupdates.com

Tracking domains:
track.yourbrandmail.com
track.yourbrandupdates.com
```

Then warm up one sending domain first. Add the second only after the first is clean and stable.

## Final Readiness Rule

Do not start real marketing sends until these four things are true:

1. SES production access is approved.
2. DKIM, SPF, DMARC, MAIL FROM, and unsubscribe are verified.
3. Bounce/complaint webhooks are flowing into Dispatch.
4. Warmup, throttle, suppression, and circuit breakers are working.

That is the line between "the app runs" and "the app can send safely."
