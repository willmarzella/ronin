# The Resume That Watches Back

---

right now you're doing what every contractor does. you write a resume. you upload it to seek. you spray it across fifty listings. you hear nothing. you change a few words. you spray again. maybe this time you hear something. maybe you don't. and when you don't, you have no idea why.

was it the resume? was it the market? was it your profile? was it that you said "data pipeline development" when they wanted "data platform engineering"? was it that a recruiter glanced at your profile at 4:47pm on a friday and your headline didn't grab them in the two seconds they gave it?

you don't know. nobody knows. that's the problem.

---

## the black box you're applying into

here's what actually happens when you hit apply on seek.

your resume and profile enter a funnel. the first gate is algorithmic — seek's internal search and ATS filtering. if your profile doesn't contain the right keyword surface, a recruiter literally never sees you. you're filtered before a human is involved. this is not a judgement of your quality. it's a keyword matching exercise run by software that doesn't understand context.

if you pass that gate, a recruiter sees your profile. not your resume — your profile. they spend maybe ten seconds on it. your headline, your summary, your most recent role title. if that doesn't pattern-match to what they're looking for, they move on. your beautifully crafted PDF attachment sits unopened.

if the profile grabs them, then maybe they open the resume. maybe they call you. maybe they email you. maybe they do nothing and you never know they looked.

the entire system is built to give you zero feedback. seek will tell you "your application was viewed" but won't tell you what happened after. rejection emails are templated and meaningless. silence is the default outcome.

so you're optimising blind. you're changing variables without knowing which variable matters. you're rewriting resumes without knowing if the resume was the problem.

the first thing we're building fixes that.

---

## wiring up the signal

gmail is the exhaust pipe of the application process. every acknowledgement, every rejection, every interview request flows through it. seek sends templated emails — "your application was viewed", "unfortunately we have decided to progress with other candidates", "we'd like to arrange a time to discuss your application." these are structured signals hiding in your inbox.

the system taps gmail, reads every email, and classifies it. rejection. interview. viewed. acknowledged. then it matches that email back to the specific job you applied for, using the job title, company name, and date proximity.

suddenly you have a funnel. you can see: out of 100 applications, 60 were never viewed (keyword problem), 25 were viewed but rejected (profile narrative problem), 10 got a response (something worked), 5 got interviews (something really worked).

that's not just data. that's a diagnostic. "never viewed" and "viewed but rejected" are completely different failure modes that require completely different fixes. right now you're treating them as the same thing — "i didn't get the job" — and responding with the same intervention: rewrite the resume and hope.

then there are the emails that don't come from seek. the hiring manager who emails you directly. the recruiter from an agency. these are harder to match because they don't contain seek's job IDs. but they do come from a company domain. `jane@woolworths.com.au` is obviously about a woolworths application. match the domain, match the title, match the date window, and you've linked the signal to the application.

over time the system builds a map of every recruiter and hiring manager who's ever contacted you. future emails from those senders match instantly.

even phone calls get captured. not automatically — you log them manually through a simple form. but the data enters the same pipeline. the signal is unified.

this is the foundation. nothing else works without it.

---

## the four shapes of work

here's where it gets interesting.

you had this taxonomy — expansion, adaptation, consolidation, aspiration — that described why a company is hiring. it's a good framework. the problem is you can't read company intent from a job description. a JD doesn't say "we're hiring because our CEO read an article about AI." it says "5+ years experience with cloud data platforms."

but there's something you can read from a job description: the shape of the work.

every data engineering role, regardless of what technologies it lists, is asking you to do one of four things.

**build something new.** the JD says "design and implement", "from the ground up", "greenfield", "architect", "establish standards." this is a company that doesn't have the thing yet and wants you to create it. they want vision, opinions, architecture decisions. your resume needs to show you've built things before and they worked.

**fix something broken.** the JD says "migrate", "modernise", "legacy", "tech debt", "consolidate", "re-platform." this is a company that has the thing but it's wrong and they want you to make it right. they want pragmatism, diplomacy, before-and-after transformations. your resume needs to show you've walked into messy situations and left them clean.

**keep something running.** the JD says "maintain", "support", "monitor", "BAU", "SLA", "reliability." this is a company that has the thing, it works, and they want you to make sure it keeps working. they want steadiness, process orientation, incident response. you probably don't want many of these.

**make something understood.** the JD says "stakeholder", "cross-functional", "self-serve", "data literacy", "business requirements", "translate." this is a company that has the thing but nobody outside the data team can use it. they want communication, enablement, patience. your resume needs to show you can bridge the gap between technical systems and the people who depend on them.

here's the critical insight: the technology keywords don't determine the archetype. the verbs around the technology keywords determine the archetype.

"snowflake" appears in all four archetypes. "implement snowflake from scratch" is builder. "migrate from redshift to snowflake" is fixer. "maintain our snowflake environment" is operator. "enable business users to self-serve from snowflake" is translator. same technology. completely different work. completely different resume needed.

the classifier reads verb-context patterns, not keyword lists. it scores every sentence in a job description against all four archetypes and produces a weighted profile: this role is 45% builder, 35% fixer, 15% translator, 5% operator. your builder resume goes out.

---

## four resumes, one you

so you write four resumes. same experience, same projects, same facts. different framing.

your builder resume leads with the time you stood up a data platform from nothing. your fixer resume leads with the time you migrated a legacy system and cut processing time by 70%. your translator resume leads with the time you built a self-serve analytics layer that eliminated 200 ad-hoc requests per month.

same career. four lenses. the system picks the right lens for each job.

and here's where git comes in. every resume version is committed to a repository. when you apply to a job, the system records which commit hash of which variant was sent. three months later, when you have outcome data, you can answer: "did builder resume version 3 perform better than version 2?" you can see exactly what the recruiter saw, matched to whether they responded.

this is the feedback loop that doesn't exist anywhere else. resume A/B testing against actual market response, with version control so you never lose what worked.

---

## the profile problem

there's a wrinkle. your seek profile is a shared resource. you have one profile. recruiters can look at it at any time. if you change it for a builder role at 9am and a fixer recruiter checks it at 2pm, they see builder language. mismatch.

the solution is batching. instead of applying to jobs one at a time, you queue them. the queue groups jobs by archetype. you process one archetype batch at a time.

monday: set profile to builder. apply to all twelve queued builder roles. wait three days. most recruiter views happen within 48-72 hours of application.

thursday: switch profile to fixer. apply to the seven queued fixer roles. wait.

it's not perfect. some recruiter will check your profile a week late and see the wrong version. that's acceptable. you're optimising for the majority case, not the edge case. and the resume they downloaded at application time is still the right one — the profile just provides additional signal.

---

## when the market moves

you've applied to a few hundred data engineering roles over several months. every job description has been embedded — turned into a mathematical vector that captures its meaning. the builder JDs cluster together in vector space. the fixer JDs cluster together. these clusters have centres.

the centre of the builder cluster in january is not the same as the centre in april. it moves. maybe in january, builder JDs emphasised airflow and on-prem deployments. by april, they're emphasising dbt and snowflake-native orchestration. the market shifted.

the system detects this by computing the cluster centre every 30 days and measuring how far it moved. if it moved more than a calibrated threshold, something changed in what the market wants from builder roles.

simultaneously, the system measures how far your builder resume is from the current cluster centre. if the market moved and your resume didn't move with it, your resume is stale.

but stale doesn't automatically mean rewrite. two conditions have to be true: the market shifted AND your resume is now far from where the market went. if the market shifted but your resume happens to still be close to the new centre, no rewrite needed. you got lucky — your existing framing still works.

and there's a cooldown. no rewrite more than once every three weeks. this prevents the system from chasing noise. markets don't shift weekly. if the metrics are jittering at the threshold boundary, the cooldown smooths it out.

when a rewrite is triggered, the system doesn't rewrite for you. it generates a report: "the builder market shifted toward [these terms] and away from [those terms]. your current resume is [this far] from the new centre. here's what to emphasise and de-emphasise." you do the rewriting. you commit the new version. the system measures the new alignment and starts tracking performance of the new version against the old.

---

## where it runs

two halves. your local machine does everything that touches seek — scraping jobs, submitting applications, updating your profile. this has to happen from your residential IP because seek blocks cloud IPs and detects automation from data centres.

everything else runs on a cheap remote server. gmail polling. email classification. archetype scoring. embedding computation. drift detection. funnel metrics. this stuff runs in the background on a schedule whether your laptop is open or not. when you sit down to apply, the queue is already sorted, the archetypes are already scored, and any drift alerts are already waiting.

your machine pulls from the remote database: "here are 12 builder roles ready to apply to, 7 fixer roles, 3 translator roles." you pick a batch, confirm, apply. the results flow back through gmail into the remote worker's email pipeline, and the feedback loop continues.

---

## what you're actually building

strip away the technical details and what you have is a system that answers three questions no contractor can currently answer:

**why am i not getting responses?** the funnel tells you whether you're failing at keyword filtering, profile narrative, or something downstream. different failure, different fix.

**which version of me works best for which type of work?** the four variants, version-controlled and tracked against outcomes, give you actual performance data on how you present yourself. not vibes. numbers.

**is the market moving away from me?** the drift detection tells you when your representation is decaying relative to what companies are actually asking for, before you notice it in your response rates.

right now you're a static resume in a dynamic market, hoping the two stay aligned by luck. what you're building is the system that keeps them aligned by measurement.

---

the execution order matters. gmail integration first. without the feedback signal, everything else is optimisation theatre — you'd be tuning a machine with no gauges. then the archetype classifier, because you need to know what you're looking at before you can respond to it. then the four resumes. then the wiring. then drift detection last, because it needs months of data flowing through the pipeline before the centroids mean anything.

don't try to build it all at once. build the signal first. let the signal tell you what to build next.
