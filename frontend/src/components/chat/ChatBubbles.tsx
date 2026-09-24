// The bubbles a conversation with an agent is drawn with, shared by the project chat with its
// Leader and the patron's direct chat with one agent (FR-007p). One set, so the two chats
// cannot drift into looking like two products.
import {
  MessagePrimitive,
  type TextMessagePartComponent,
} from '@assistant-ui/react';
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown';
import { cn } from '@/lib/utils';

// assistant-ui markdown renderer. MarkdownTextPrimitive reads the part text from
// context, so the wrapper takes no props — it just satisfies the Text part
// component contract. `smooth` enables the typing animation as tokens stream in.
const MarkdownText: TextMessagePartComponent = () => (
  <MarkdownTextPrimitive smooth />
);

// Patron (user) bubble — right-aligned, terracotta. Plain text (patron's own words,
// no markdown rendering).
export function PatronBubble() {
  return (
    <MessagePrimitive.Root className="flex justify-end">
      <div className="max-w-[85%] rounded-lg px-3 py-1.5 bg-terracotta text-white font-body text-body-sm whitespace-pre-wrap break-words">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
}

// A wake the platform delivered into the conversation — centred, quiet, and deliberately
// not a bubble: nobody said it, so giving it a speaker's shape would be a lie. It used to
// arrive dressed as the Leader talking to itself.
export function SystemNotice() {
  return (
    <MessagePrimitive.Root className="flex justify-center">
      <div className="max-w-[92%] rounded-md px-2.5 py-1 bg-vellum border border-dashed border-vellum-dark text-ink-muted font-body text-body-xs text-center whitespace-pre-wrap break-words">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
}

// Agent (assistant) bubble — left-aligned, vellum-deep. Text parts render as
// Markdown (code, lists, headings, links) styled to match the brand via arbitrary
// Tailwind variants (no @tailwindcss/typography dependency).
export function AgentBubble() {
  return (
    <MessagePrimitive.Root className="flex justify-start">
      <div
        className={cn(
          'max-w-[90%] rounded-lg px-3 py-1.5 bg-vellum-deep border border-vellum-dark text-ink font-body text-body-sm break-words',
          '[&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0',
          '[&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-0.5',
          '[&_code]:font-mono [&_code]:text-[0.85em] [&_code]:bg-vellum [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded',
          '[&_pre]:my-1 [&_pre]:bg-vellum [&_pre]:border [&_pre]:border-vellum-dark [&_pre]:rounded-md [&_pre]:p-2 [&_pre]:overflow-x-auto [&_pre_code]:bg-transparent [&_pre_code]:p-0',
          '[&_a]:text-terracotta [&_a]:underline [&_h1]:font-display [&_h1]:text-body-md [&_h1]:my-1',
          '[&_h2]:font-display [&_h2]:text-body-sm [&_h3]:font-display [&_h3]:text-body-sm [&_h4]:font-display [&_h4]:text-body-sm',
          '[&_blockquote]:my-1 [&_blockquote]:border-l-2 [&_blockquote]:border-vellum-dark [&_blockquote]:pl-2 [&_blockquote]:text-ink-light',
          '[&_strong]:font-semibold [&_em]:italic [&_hr]:my-2 [&_hr]:border-vellum-dark',
        )}
      >
        <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
      </div>
    </MessagePrimitive.Root>
  );
}
