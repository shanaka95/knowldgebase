import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"

import { APP_NAME } from "@/components/Common/Logo"
import { Bullets, LegalPage, Section } from "@/components/Legal/LegalPage"

/**
 * What this installation does with what people put into it.
 *
 * Written against the product as it actually behaves - the model providers it
 * calls, the metering it keeps, the two-factor email it sends - rather than
 * from a template. The blanks are marked rather than guessed: a policy naming
 * the wrong legal entity is worse than one that visibly needs filling in.
 */

export const Route = createFileRoute("/privacy")({
  component: Privacy,
  head: () => ({
    meta: [{ title: `Privacy Policy - ${APP_NAME}` }],
  }),
})

function Privacy() {
  return (
    <LegalPage
      title="Privacy Policy"
      intro={
        <>
          This policy explains what {APP_NAME} collects, why, where it goes, and
          what you can do about it. It describes the service as it actually
          works rather than in the abstract.
        </>
      }
    >
      <Section id="who" title="Who we are">
        <p>
          {APP_NAME} is operated by <strong>Shanaka Anuradha</strong>,
          Stuttgarter Str. 15, 74074 Heilbronn, Germany. For anything in this
          policy, including a request to see or delete your data, write to{" "}
          <a href="mailto:admin@plusgpt.io">admin@plusgpt.io</a>. Full provider
          details are on the <RouterLink to="/imprint">Imprint</RouterLink>.
        </p>
        <p>
          Where data protection law gives you rights against a{" "}
          <strong>controller</strong>, that controller is the entity named above
          for account data, and your own organisation for the documents you
          upload.
        </p>
      </Section>

      <Section id="what" title="What we collect">
        <p>Three kinds of thing, for three different reasons.</p>
        <p className="font-medium">Your account</p>
        <Bullets
          items={[
            "Your email address, and your name if you give one.",
            "A hash of your password — never the password itself.",
            "Sign-in codes sent to your email, which expire and are then discarded.",
            "API keys you create, stored hashed. The key itself is shown once and never again.",
          ]}
        />
        <p className="font-medium">What you put in</p>
        <Bullets
          items={[
            "The pages you write, the files you upload, and the original files themselves.",
            "Notes you add to a page, with your name and the time you wrote them.",
            "Spaces, folders, and who you have shared them with.",
            "Questions you ask, and the answers given, kept as conversation history so a thread can be reopened.",
          ]}
        />
        <p className="font-medium">How the service is used</p>
        <Bullets
          items={[
            "Counts of what you did — questions asked, searches run, pages imported — by day and by model, together with the tokens and cost each involved.",
            "Operational logs and error reports needed to keep the service running.",
          ]}
        />
        <p>
          We do not use advertising trackers, we do not sell anything to
          anybody, and we do not build profiles of you for marketing.
        </p>
      </Section>

      <Section id="ai" title="AI models, and what is sent to them">
        <p>
          This is the part worth reading closely, because it is the part where
          your content leaves this installation.
        </p>
        <p>
          To make a page searchable and to answer questions about it, {APP_NAME}{" "}
          sends text to a model provider. Depending on how this installation is
          configured that provider is either <strong>a third party</strong> (for
          example an API gateway such as OpenRouter, which routes to the model
          vendor actually serving the request) or{" "}
          <strong>a model running on our own infrastructure</strong>, in which
          case nothing leaves it.
        </p>
        <p>What gets sent, and when:</p>
        <Bullets
          items={[
            "When a page is indexed: its title, its text, and any notes on it — to be summarised, split into sections, and turned into vectors.",
            "When a file is imported: an image of each page, so a model can transcribe it.",
            "When you ask a question: your question, the recent turns of that thread, and excerpts of the pages found to be relevant.",
            "When you translate a page: that page's text.",
          ]}
        />
        <p>
          This installation uses <strong>OpenRouter</strong>, which routes each
          request to the model vendor serving it. We do not permit providers to
          train models on content sent from this service. OpenRouter and the
          vendors behind it keep their own logs under their own terms, and their
          privacy policies also apply to the request.
        </p>
      </Section>

      <Section id="why" title="Why we are allowed to hold it">
        <Bullets
          items={[
            <>
              <strong>To provide the service</strong> — storing, indexing,
              searching and sharing what you put in. Without this there is no
              product.
            </>,
            <>
              <strong>To keep accounts secure</strong> — sign-in codes, password
              hashing, and records of access.
            </>,
            <>
              <strong>To run the service responsibly</strong> — usage counts and
              limits, so one account cannot exhaust the service or the budget
              for everybody else.
            </>,
            <>
              <strong>To meet legal obligations</strong>, where any apply.
            </>,
          ]}
        />
      </Section>

      <Section id="who-sees" title="Who can see your content">
        <Bullets
          items={[
            "You, always.",
            "People you share a space, folder or page with, at the level you gave them.",
            "Anybody holding a public link you created, for as long as it is on. Turning link sharing off and on again issues a new link and breaks the old one.",
            <>
              <strong>Administrators of this installation</strong>, who can see
              account details, group membership and usage figures including
              cost. Administrators can reach content when they need to operate
              or support the service.
            </>,
            "Service providers we depend on to run it — see below.",
          ]}
        />
        <p>
          Usage figures shown to <em>you</em> never include cost. Group
          membership is an administrative matter and is not shown to members.
        </p>
      </Section>

      <Section id="processors" title="Who we rely on">
        <p>
          {APP_NAME} needs a few services to function. Each sees only what it
          needs to:
        </p>
        <Bullets
          items={[
            <>
              <strong>OpenRouter</strong> — the model calls described above.
            </>,
            <>
              <strong>Amazon Web Services (Amazon SES)</strong> — delivering
              sign-in codes, invitations and password resets.
            </>,
            <>
              <strong>Our server hosting provider</strong> — the virtual servers
              holding the database, the uploaded files and the search index.
            </>,
          ]}
        />
        <p>
          Data is held and processed in the{" "}
          <strong>United States and Europe</strong>. Where personal data is
          transferred outside the EEA, we rely on the European Commission's{" "}
          <strong>standard contractual clauses</strong>, together with the
          additional safeguards those clauses require.
        </p>
      </Section>

      <Section id="keeping" title="How long we keep it">
        <Bullets
          items={[
            "Pages, files and notes: until you delete them. Deleting a page removes its text, its search index entries, its notes and its version history.",
            "Question threads: until you delete them, and in any case only the most recent are kept per account.",
            "Usage records: kept as a history of what an account used, so figures for past months stay meaningful.",
            "Sign-in codes: minutes.",
            <>
              <strong>Closing your account</strong> removes it, its usage
              records and the pages you alone could see. Notes you left on pages
              that still exist remain, without your name against them — a note
              is part of a page's history, and removing an account should not
              silently change what a page says.
            </>,
          ]}
        />
      </Section>

      <Section id="rights" title="Your rights">
        <p>
          Depending on where you live, you can ask for a copy of your data, ask
          for it to be corrected or deleted, object to how it is used, or ask
          for it in a portable form. Most of this you can do yourself from{" "}
          <strong>Settings</strong>; for the rest, write to the address at the
          top of this policy and we will respond <strong>within 30 days</strong>
          .
        </p>
        <p>
          If you think we have got something wrong you can complain to your
          local data protection authority. Ours is{" "}
          <strong>
            Der Landesbeauftragte für den Datenschutz und die
            Informationsfreiheit Baden-Württemberg
          </strong>
          , Lautenschlagerstraße 20, 70173 Stuttgart.
        </p>
      </Section>

      <Section id="security" title="Security">
        <Bullets
          items={[
            "Signing in needs a password and a code sent to your email address. A password alone is not enough.",
            "Passwords are stored hashed. API keys are stored hashed and shown once.",
            "Traffic is encrypted in transit.",
            "Access to a page is checked on every request, not only when it is opened.",
          ]}
        />
        <p>
          No service is perfectly secure. If you find a vulnerability, please
          tell us at{" "}
          <a href="mailto:incident@plusgpt.io">incident@plusgpt.io</a> before
          telling anybody else.
        </p>
      </Section>

      <Section id="cookies" title="Cookies and local storage">
        <p>
          {APP_NAME} stores your sign-in token and a few preferences — your
          theme, your search settings, which panel you had open — in your
          browser. They are needed for the service to work and to remember how
          you like it. There are no advertising or analytics cookies.
        </p>
      </Section>

      <Section id="children" title="Children">
        <p>
          {APP_NAME} is not intended for anyone under <strong>16</strong>, and
          we do not knowingly collect their data. If you believe a child has
          given us personal data, write to{" "}
          <a href="mailto:admin@plusgpt.io">admin@plusgpt.io</a> and we will
          delete it.
        </p>
      </Section>

      <Section id="changes" title="Changes">
        <p>
          If this policy changes in a way that matters, we will say so before
          the change takes effect. The date at the top always reflects the
          current version.
        </p>
        <p>
          See also the <RouterLink to="/terms">Terms of Service</RouterLink>.
        </p>
      </Section>
    </LegalPage>
  )
}
