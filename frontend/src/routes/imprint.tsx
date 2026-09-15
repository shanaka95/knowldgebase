import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"

import { APP_NAME } from "@/components/Common/Logo"
import { LegalPage, Placeholder, Section } from "@/components/Legal/LegalPage"

/**
 * Impressum — provider identification under § 5 DDG.
 *
 * Not optional decoration: a commercial online service operated from Germany
 * has to name its provider, and the details have to be easy to find, directly
 * reachable and permanently available. That is why this is its own page linked
 * from every footer rather than a paragraph inside the terms.
 */

export const Route = createFileRoute("/imprint")({
  component: Imprint,
  head: () => ({
    meta: [{ title: `Imprint - ${APP_NAME}` }],
  }),
})

function Imprint() {
  return (
    <LegalPage
      title="Imprint"
      intro={
        <>
          Provider identification for {APP_NAME}, under § 5 of the German
          Digital Services Act (DDG) and § 18 (2) of the Interstate Media Treaty
          (MStV).
        </>
      }
    >
      <Section id="provider" title="Angaben gemäß § 5 DDG">
        <address className="not-italic leading-relaxed">
          <strong>Shanaka Anuradha</strong>
          <br />
          Stuttgarter Str. 15
          <br />
          74074 Heilbronn
          <br />
          Germany
        </address>
      </Section>

      <Section id="contact" title="Contact">
        <p>
          Email: <a href="mailto:admin@plusgpt.io">admin@plusgpt.io</a>
          <br />
          Security reports:{" "}
          <a href="mailto:incident@plusgpt.io">incident@plusgpt.io</a>
        </p>
      </Section>

      <Section id="responsible" title="Responsible for content (§ 18 (2) MStV)">
        <p>Shanaka Anuradha, at the address above.</p>
      </Section>

      <Section id="vat" title="VAT">
        <p>
          VAT identification number under § 27 a of the German VAT Act
          (Umsatzsteuergesetz):{" "}
          <Placeholder>
            [USt-IdNr., or delete this section if you are a Kleinunternehmer
            without one]
          </Placeholder>
        </p>
      </Section>

      <Section id="disputes" title="Dispute resolution">
        <p>
          The European Commission provides a platform for online dispute
          resolution at{" "}
          <a
            href="https://ec.europa.eu/consumers/odr"
            target="_blank"
            rel="noreferrer"
          >
            ec.europa.eu/consumers/odr
          </a>
          . We are not obliged, and are not willing, to take part in dispute
          resolution proceedings before a consumer arbitration board.
        </p>
      </Section>

      <Section id="more" title="See also">
        <p>
          <RouterLink to="/privacy">Privacy Policy</RouterLink> ·{" "}
          <RouterLink to="/terms">Terms of Service</RouterLink>
        </p>
      </Section>
    </LegalPage>
  )
}
