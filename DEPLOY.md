# Putting the demo online

How to give people a link to the PO Intake demo. The online version holds made-up data
only, plays back the 5 sample POs without AI, never sends email, and a password keeps it
to the people you send it to.

## What runs online

`python -m app.hosted` starts one web service: the pipeline app on the port the host gives
it, with the demo ERP running inside the same service and reachable at `/erp`. The
settings in `render.yaml` make it:

| Setting | Value | Why |
|---|---|---|
| `PO_EXTRACTOR` | `replay` | The 5 samples, no AI, no API key, no cost. Other PDFs show a message. |
| `SEND_MODE` | `dry` | Confirmation emails are saved to the customer folder, never sent. |
| `DEMO_PASSWORD` | you choose | Turns on the password page. Always set it on a public host. |
| `SESSION_SECRET` | Render generates it | Keeps visitors signed in across restarts. |

The mailbox watcher is always off online. Open folder shows the saved files in the browser.

## Steps on Render

1. Create a Render account at render.com (your account; you do this).
2. **New → Blueprint**, connect GitHub, and pick this repository. Render reads `render.yaml`.
3. When it asks for `DEMO_PASSWORD`, type a password you make up (three random words work
   well). Share it only together with the link.
4. Apply. The first deploy takes a minute or two. Render shows the link, like
   `https://po-intake-demo.onrender.com`.
5. Open the link, type the password, pick a sample, and run it through to the email.

Every push to `main` then updates the online demo by itself.

## Keeping it awake

Render's free plan puts the service to sleep after 15 minutes without visitors; the next
visit then takes about a minute. `.github/workflows/keep-awake.yml` visits `/healthz` every
10 minutes to prevent that. Turn it on by adding a repository variable:

- GitHub → this repository → Settings → Secrets and variables → Actions → **Variables** →
  New repository variable: name `DEMO_URL`, value the Render link.

Or from a terminal: `gh variable set DEMO_URL --body "https://po-intake-demo.onrender.com"`.

GitHub sometimes starts scheduled runs late, so the demo may still nap now and then. GitHub
also pauses schedules in a repository with no activity for 60 days; re-enable the workflow
under the Actions tab if that happens.

## Sending it to people

> Here's a demo of PO Intake: https://po-intake-demo.onrender.com
> Password: (the demo password)
> Click **Try a sample**, wait for Claude's step to finish, then **Open review** and **Accept**.

## Good to know

- Everyone who opens the link shares one pipeline, so two people using it at the same
  moment see each other's run. Reset clears it.
- Orders, CRM changes and saved files live on the server's own disk. Render's free plan
  wipes them whenever the service restarts or redeploys, which gives a fresh demo.
- Changing `DEMO_PASSWORD` in Render signs everyone out.
- To read any PDF with real Claude extraction online, set `PO_EXTRACTOR` to `api` and add
  an `ANTHROPIC_API_KEY` in Render. Each PO is then billed to that key.
