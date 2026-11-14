// The bubbles a conversation with an agent is drawn with, shared by the project chat with its
// Leader and the patron's direct chat with one agent (FR-007p). One set, so the two chats
// cannot drift into looking like two products.
import {
  MessagePrimitive,
  type TextMessagePartComponent,
} from '@assistant-ui/react';
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown';
import type { ComponentPropsWithoutRef, ReactNode } from 'react';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

// The row one message sits in. A plain element, deliberately not `MessagePrimitive.Root`.
//
// The library's root does two things beyond being a `div`: it registers the row as a scroll
// anchor (only for the top-anchored layout, which these chats do not use) and it tracks
// whether the pointer is over the message, for an action bar that appears on hover. These
// chats have no action bar, so the hover state has no reader — and writing it throws: with
// the external-store runtime the per-message store is never mounted, and every pointer
// crossing a bubble raised "Resource updated before mount" as an uncaught page error
// (found 2026-11-12; measured again 2026-11-13, one error per bubble crossed). Newer builds
// of the library's internals turn the same write into an update loop, so upgrading is not
// the way out. The message *content* still comes from the library (`MessagePrimitive.Parts`).
function MessageRow({ className, children }: { className: string; children: ReactNode }) {
  return <div className={className}>{children}</div>;
}

// assistant-ui markdown renderer. MarkdownTextPrimitive reads the part text from
// context, so the wrapper takes no props — it just satisfies the Text part
// component contract. `smooth` enables the typing animation as tokens stream in.
//
// GitHub-flavoured markdown is switched on because agents answer in it: a Leader proposing
// work lays the tasks out as a pipe table, and without the plugin the table arrived as one
// paragraph of words and `|` (seen 2026-11-14 in the CALC project chat). The plugin list is
// a module constant so the renderer is not handed a new array on every streamed token.
const REMARK_PLUGINS = [remarkGfm];

// A table is the one thing in a bubble that cannot wrap to the bubble's width, so it gets
// its own scroll box: a wide table scrolls inside the bubble instead of widening the page.
function ScrollingTable(props: ComponentPropsWithoutRef<'table'>) {
  return (
    <div className="my-2 max-w-full overflow-x-auto rounded-md border border-line">
      <table {...props} />
    </div>
  );
}

const MARKDOWN_COMPONENTS = { table: ScrollingTable };

const MarkdownText: TextMessagePartComponent = () => (
  <MarkdownTextPrimitive smooth remarkPlugins={REMARK_PLUGINS} components={MARKDOWN_COMPONENTS} />
);

// Patron (user) bubble — right-aligned, sapphire-soft (the patron's colour in the design). Plain text (patron's own words,
// no markdown rendering).
export function PatronBubble() {
  return (
    <MessageRow className="flex justify-end">
      <div className="max-w-[85%] rounded-[13px] rounded-tr-[4px] border border-sapphire/30 bg-sapphire-soft px-4 py-2.5 text-ink font-body text-[14px] leading-[1.7] whitespace-pre-wrap break-words">
        <MessagePrimitive.Parts />
      </div>
    </MessageRow>
  );
}

// A wake the platform delivered into the conversation — centred, quiet, and deliberately
// not a bubble: nobody said it, so giving it a speaker's shape would be a lie. It used to
// arrive dressed as the Leader talking to itself.
export function SystemNotice() {
  return (
    <MessageRow className="flex justify-center">
      <div className="max-w-[92%] rounded-md px-3 py-1.5 bg-canvas-deep border border-dashed border-line-strong text-ink-muted font-body text-body-sm text-center whitespace-pre-wrap break-words">
        <MessagePrimitive.Parts />
      </div>
    </MessageRow>
  );
}

// Agent (assistant) bubble — left-aligned, on the field colour with a hairline. Text parts render as
// Markdown (code, lists, headings, links, tables) styled to match the brand via arbitrary
// Tailwind variants (no @tailwindcss/typography dependency).
export function AgentBubble() {
  return (
    <MessageRow className="flex justify-start">
      <div
        className={cn(
          'max-w-[90%] rounded-[13px] rounded-tl-[4px] px-4 py-2.5 bg-field border border-line text-ink font-body text-[14px] leading-[1.7] break-words',
          '[&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0',
          '[&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-0.5',
          '[&_code]:font-mono [&_code]:text-[0.85em] [&_code]:bg-canvas-deep [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded',
          '[&_pre]:my-1 [&_pre]:bg-canvas-deep [&_pre]:border [&_pre]:border-line [&_pre]:rounded-md [&_pre]:p-2 [&_pre]:overflow-x-auto [&_pre_code]:bg-transparent [&_pre_code]:p-0',
          '[&_a]:text-sapphire-strong [&_a]:underline [&_h1]:font-display [&_h1]:text-body-md [&_h1]:my-1',
          '[&_h2]:font-display [&_h2]:text-body-sm [&_h3]:font-display [&_h3]:text-body-sm [&_h4]:font-display [&_h4]:text-body-sm',
          '[&_blockquote]:my-1 [&_blockquote]:border-l-2 [&_blockquote]:border-line-strong [&_blockquote]:pl-2 [&_blockquote]:text-ink-light',
          '[&_strong]:font-semibold [&_em]:italic [&_hr]:my-2 [&_hr]:border-line',
          '[&_table]:w-full [&_table]:border-collapse [&_table]:text-[13px] [&_table]:leading-[1.5]',
          '[&_th]:bg-canvas-deep [&_th]:px-2.5 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-semibold [&_th]:align-bottom',
          '[&_td]:px-2.5 [&_td]:py-1.5 [&_td]:align-top [&_td]:border-t [&_td]:border-line',
          '[&_th+th]:border-l [&_th+th]:border-line [&_td+td]:border-l',
          '[&_del]:text-ink-muted [&_input[type=checkbox]]:mr-1.5 [&_input[type=checkbox]]:align-middle',
        )}
      >
        <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
      </div>
    </MessageRow>
  );
}
