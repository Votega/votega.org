/**
 * The votega:// resources (spec §8): about, glossary and datasets. Their text is written once,
 * in _data/mcp.yml and _data/open_data.yml; build_mcp_index.py turns it into resources.json at
 * deploy, and the /ai-assistants/ page renders the same YAML, so the two cannot drift.
 */
import type { Loader } from "./data";
import { stripControls } from "./util";

export type ResourcesDoc = {
  metadata: { generatedAt: string };
  about: {
    summary: string;
    principles: string[];
    covers: string[];
    not_yet: string[];
    license: string;
    corrections: string;
    page_url: string;
  };
  glossary: { term: string; definition: string }[];
  datasets: {
    intro: string | null;
    page_url: string;
    license: string;
    datasets: {
      id: string;
      title: string | null;
      summary: string | null;
      source: string | null;
      scope: string | null;
      cadence: string | null;
      repo_url: string | null;
      docs_url: string | null;
      files: { name: string | null; description: string | null; url: string | null }[];
    }[];
  };
};

export const RESOURCES = [
  {
    name: "about",
    uri: "votega://about",
    title: "About VoteGA",
    description: "What VoteGA is, its nonpartisan policy and sources, what the server covers and does not, and the license.",
    mimeType: "text/plain",
  },
  {
    name: "glossary",
    uri: "votega://glossary",
    title: "Glossary",
    description: "Office and district terms, including why a ZIP code or county is not a district, and VoteGA's ids.",
    mimeType: "text/plain",
  },
  {
    name: "datasets",
    uri: "votega://datasets",
    title: "Open datasets",
    description: "VoteGA's published datasets (CC BY-SA 4.0): what each holds, its source, update cadence and files.",
    mimeType: "application/json",
  },
] as const;

export type ResourceName = (typeof RESOURCES)[number]["name"];

const bullets = (items: string[]) => items.map((x) => `- ${x}`).join("\n");

export function renderAbout(d: ResourcesDoc): string {
  const a = d.about;
  return [
    "ABOUT VOTEGA",
    a.summary,
    "",
    "PRINCIPLES",
    bullets(a.principles),
    "",
    "WHAT THE SERVER COVERS",
    bullets(a.covers),
    ...(a.not_yet.length ? ["", "NOT YET AVAILABLE THROUGH THE SERVER", bullets(a.not_yet)] : []),
    "",
    "LICENSE",
    a.license,
    "",
    "CORRECTIONS",
    a.corrections,
    "",
    `More: ${a.page_url}`,
    `Data built: ${d.metadata.generatedAt}`,
  ].join("\n");
}

export function renderGlossary(d: ResourcesDoc): string {
  return ["GLOSSARY", ...d.glossary.map((g) => `\n${g.term}\n${g.definition}`)].join("\n");
}

export function renderDatasets(d: ResourcesDoc): string {
  return JSON.stringify({ ...d.datasets, as_of: d.metadata.generatedAt });
}

export async function readResource(loader: Loader, name: ResourceName, uri: string) {
  const doc = await loader.load<ResourcesDoc>("resources.json");
  const text = !doc
    ? "VoteGA's resources are unavailable right now. See https://www.votega.org/ai-assistants/."
    : name === "about"
      ? renderAbout(doc)
      : name === "glossary"
        ? renderGlossary(doc)
        : renderDatasets(doc);
  const mimeType = RESOURCES.find((r) => r.name === name)!.mimeType;
  // Our own text, but it gets the same control-character hygiene as tool results. No length cap:
  // a dataset summary can run past the 500 characters tool fields are held to.
  return { contents: [{ uri, mimeType, text: stripControls(text) }] };
}
