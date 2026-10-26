# Ocra Pipeline Tracker: user manual for managers

This guide is organized around the questions managers usually bring to the app. You don't need any technical knowledge. For installation and setup, see [README.md](README.md).

> **Remember our starting point: All life matters.** The Overview opens with our mission and values. You can edit them under Settings and Activity → Mission and values.

---

## 1. Opening the app

1. Ask the person who runs the app to start it, or run `./scripts/start.sh` yourself (README §4).
2. Open **http://127.0.0.1:8000** in your browser.
3. To switch language, click **EN / 中文** in the top-right corner. The app remembers your choice, and the AI Assistant answers in that language.

The coloured bar under the page title shows the **mode**:
- **Demo mode** means every record is fictional and no AI is called.
- **Live mode** means the app searches real public sources and calls the AI model.

If a database contains demonstration records, the bar says so.

---

## 2. Finding your way

The menu on the left is grouped by the question you have. It always fits on one screen. The line under each page name tells you what that page answers.

| If you want to know… | Go to |
|---|---|
| The big picture and today's priorities | **Start here → Overview** |
| What we are developing and what happens next | **Our science → Pipelines** |
| How much cash we have, how long it lasts, and whether we can afford the next milestone | **Our money → Budget and Runway** |
| What is new today | **Outside world → Daily Briefing** |
| What our competitors are doing | **Outside world → Competitor Intelligence** |
| Which rules and guidance apply to us | **Outside world → Regulatory Intelligence** |
| Who could license or partner with us | **Outside world → Markets and Licensing** |
| Anything else, in plain words | **Get help → AI Assistant** |
| Who changed what, and what the AI has done | **Get help → Settings and Activity** |

At the top of each page, "You are here" shows where you are. Under the title, **Related** links take you to the next page you will probably need.

---

## 3. The Overview: your morning check (2 minutes)

The Overview answers eight questions on cards. Each card gives a one-line answer and a button to the page with the details:

- **Can we fund our next milestones?** Green means funded, red means there is a funding gap, and grey means we can't tell yet (usually because the milestone has no budget).
- **How long does our cash last?** Shows the month projected cash falls below our minimum reserve.
- **What are we developing, and what is next?**
- **What is new today?**
- **What are competitors doing?**
- **Which rules could affect our plans?**
- **Who could license our products?**
- **I have a different question.** Opens the AI Assistant.

Below the cards you will find the next milestone for each pipeline, the projected-cash chart, and the latest outside news.

Once a day a short **briefing popup** may appear. Read it, then click **Dismiss for today**.

---

## 4. Our science: Pipelines

- The list shows our three pipelines with their stage, regions and next milestone.
- The **development phase map** below the list shows where each pipeline stands.
  - **Down the side:** our pipelines.
  - **Across the top:** the twelve phases of developing a veterinary medicine.
    1. Discovery
    2. Lead optimization
    3. Patent filing
    4. Preclinical / PK
    5. CMC (manufacturing)
    6. INAD / regulatory advice
    7. GLP target animal safety
    8. Pilot field efficacy (GCP)
    9. Pivotal field efficacy (GCP)
    10. Dossier and filing
    11. Approval
    12. Launch
  - **Milestones** sit in the phase they belong to and show their status, end date and any funding gap. The pipeline's current phase is outlined.
  - **Diamonds** mark the value-inflection points: moments when a major risk is retired and the asset becomes worth more. Examples are a nominated development candidate, a patent filing, the GLP safety package and clinical proof of concept. That is where a go / no-go decision, and often a financing or partnering conversation, belongs.
    - A small teal **paw print** means the gate is passed.
    - An **amber**, pulsing diamond is the next decision.
    - A **dashed teal** diamond means the work for that phase is done, but an earlier gate is still open. For example, a provisional patent may be filed before the development candidate is nominated. Gates are passed **in order**, so this one only becomes a paw once every earlier gate is passed.
    - An **outlined** diamond is still ahead.
  - A milestone's phase comes from its **Stage** field. If that is empty, the app infers the phase from the milestone name, so set the Stage when you add a milestone.
  - On a narrow screen, scroll sideways to see all twelve phases.
- Click a pipeline to see its milestones, budget and funding status, plus buttons to refresh its competitor, regulatory and partner research.
- **Adding a new program:** click **+ New program**, type a few sentences about it, then click **Propose profile**.
  - The AI fills in species, indication, modality, regions and so on. Each field is marked *stated* (you said it), *inferred* (the AI guessed it), or *unknown*.
  - Correct anything that is wrong, then click **Create program and confirm reviewed profile**.
  - Research only starts after you confirm. Only non-confidential profile fields (species, indication, type of molecule) are ever used in public searches.

---

## 5. Our money: Budget and Runway

Start on the **Summary** tab.

**The four numbers at the top**

| Number | Meaning |
|---|---|
| Available cash | The bank balances we last checked against statements, plus every transaction since. |
| Gross burn / month | Average money going out each month (last 3 full months by default; you can change the period). |
| Net burn / month | Money out minus money in (refunds count as money in). Investment rounds and transfers between our own accounts are left out. The line under it shows the *simple runway* (cash ÷ net burn). |
| Forecast runway | The first month our projected cash drops below the minimum reserve, and the month it drops below zero. This is more realistic than the simple runway because it includes the studies and contracts already planned. |

**Actual spend to date vs. estimate to complete, by pipeline and milestone**

There is one card for each of our three pipelines. For every milestone:
- the **teal** part of the bar is the **actual spend to date** (money already paid);
- the **blue** part is the **estimate to complete (ETC)**: contracts signed but not yet paid, plus the budget still left;
- the small grey text gives the budget and whether it is approved or still a draft.

"**No budget yet**" means nobody has entered costs for that milestone. Until someone does, the forecast leaves it out. A completed milestone with no costs (for example, a patent filing paid outside the app) says "Completed · no costs recorded".

Company running costs (payroll, rent, overhead) don't belong to any one pipeline. They are listed in one line under the cards.

**Other tabs, when you need them**

| Tab | Use it to… |
|---|---|
| What-if scenarios | Test a delay, a cost change or new funding, for example "Pilot study starts 3 months later". Scenarios never change the real plan. |
| Milestone budgets | Add a budget line (**+ Add budget line**, then **Save as draft**) and approve it (**Approve**). Every approval is logged. |
| Import bank data | Upload a CSV or Excel export from the bank or ledger. The app checks every row and flags duplicates, unclear dates, transfers between our own accounts, and refunds. You see a summary before anything is saved (**Confirm and import**). A mistaken import can be undone with **Reverse batch**. |
| Transactions | Check or correct which pipeline or milestone a payment belongs to. |
| Commitments and flows | Contracts signed but not yet paid, expected grants or investments, and rules for sharing costs. |
| Cash, FX and settings | Enter a bank balance from a statement (**Record balance**), update exchange rates (**Fetch ECB reference rates**), and set the minimum reserve and reporting currency. |

**Monthly housekeeping (10 minutes).** These steps keep the numbers trustworthy:
1. Import last month's bank exports.
2. Record each account's month-end statement balance.
3. Click **Fetch ECB reference rates**.
4. Check that every open milestone has a budget, and approve budgets once they are agreed.

**Exporting.** **Export summary + assumptions (CSV)** and **Export transactions (CSV)** create files for the board pack or the accountant.

> These figures are a management view. They are not audited or statutory accounts. The AI never calculates them; ordinary, tested code does.

---

## 6. Outside world

### Daily Briefing
The day's lead story plus short sections on animal health, regulation, pipelines, and our own reminders (milestones due, cash). Each item links to its source and shows its date. **Refresh now** fetches the latest.

### Competitor Intelligence
Open the **Competitors by pipeline** tab first. Each pipeline has one card listing:
- **Competitor:** the company we watch.
- **Product:** their competing product and its stage.
- **Latest movement:** their most recent public event we have found, such as a trial, approval, deal or financing, with a source link and dates.

"**Latest related news**" is news in the same disease area that doesn't name a tracked competitor.

The other tabs:
- **All news** is the full timeline. Each item keeps what the source says apart from the AI's interpretation.
- **Follow-ups** holds actions the AI proposed or the team added. Only people accept or close them.
- **Add or manage competitors** lets you add a company yourself, or track or dismiss companies the AI suggests.

### Regulatory Intelligence
Official guidance from agencies such as FDA CVM, EMA, MARA and MAFF. Each document shows whether it is a draft or final and whether it is binding or only guidance. It also shows the exact quoted passages and the questions a regulatory specialist should confirm. Milestones that may be affected are flagged for review; the plan itself never changes automatically. **Authorities and coverage** lists which agency is responsible in each region and which sources need a manual check.

### Markets and Licensing
Reported revenue of the large animal-health companies (from public filings; this is not market share). It also lists possible partners, with a fit score based only on documented evidence.

---

## 7. Asking the AI Assistant

Type a question in plain words, or click one of the examples, such as:
- "Can we afford the next milestone?"
- "What happens to runway if the pilot study starts three months later?"
- "Which regulatory updates might affect our canine program?"

Choose a **Context program** first if your question is about one pipeline.

Each answer shows:
- **Key figures**, taken directly from the app's calculations, with the tool that produced each one;
- **Sources** for anything external;
- **Assumptions** and **Gaps and data warnings**, meaning what the answer could not check;
- **Suggested for human review.**

The assistant can **only read**. It cannot change budgets, milestones or transactions.

---

## 8. What the labels mean

| Label | Meaning |
|---|---|
| Internal / Imported | Entered by our team, or imported from our spreadsheets |
| External source | From a public website. Check the link and date. |
| AI interpretation / AI research | Written by the AI. Review it before relying on it. |
| Planning assumption | An estimate, not a fact |
| Hypothesis | Deliberately speculative, for example a competitor's possible next move |
| Synthetic demo / Demo fixture | Fictional demonstration data |

---

## 9. Good habits

- Treat AI text as a first draft. Numbers come from the calculations, and judgments stay with us.
- Don't paste confidential details (real program names, partners, amounts) into public-facing fields. The app blocks them from web searches, but care still matters.
- Review the **Follow-ups** queue weekly and give each item an owner.
- Before a board or investor meeting, do the monthly housekeeping (§5) so that cash and runway are current.

---

## 10. If something looks wrong

| You see | Do this |
|---|---|
| "Cannot reach the backend" or the page doesn't load | The app isn't running. Ask whoever runs it to start it (README §4), then refresh the page. |
| Available cash shows "Incomplete" | An account has no checked balance. Go to Budget and Runway → Cash, FX and settings → **Record balance**. |
| A milestone shows "unknown" funding or "No budget yet" | Add a budget line under Milestone budgets. |
| A number looks too high or too low | Check the Transactions tab for payments assigned to the wrong pipeline, or reverse a mistaken import. |
| Research returns nothing new | That is normal on quiet days. The app only reports what the public sources it searched contain. |
| "Model not ready" in the mode bar | The AI key is missing or wrong. Ask whoever runs the app to check the setup (README §3). |

For anything else, open **Settings and Activity → Activity log** to see who changed what and when.
