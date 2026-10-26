// What a person may set on one agent, drawn from what the place it works at answered
// (FR-007k, FR-017). Nothing here is keyed on which CLI it is — the list arrives as data,
// and a place that offered nothing simply draws nothing.
//
// One component because there are two screens: choosing settings for a new agent, and
// changing them on one that exists. Two copies of this would be two renderings of the same
// data, and the one that drifts is the one nobody is looking at.
//
// Since 2026-10-26 a setting can narrow another — each Claude Code model says which thinking
// levels it takes — and the narrowing is applied here as the person picks, through the pure
// rules in `lib/runtimeOptions.ts`: a level the new model does not take goes back to blank
// rather than waiting to be refused.
import { useTranslation } from 'react-i18next';
import type { PlacementOption } from '@/store/appStore';
import { choose, isClosed, labelOf, offeredValues } from '@/lib/runtimeOptions';
import Dropdown from '@/components/Dropdown';
import SuggestBox from '@/components/SuggestBox';

export default function RuntimeOptionFields({
  options,
  chosen,
  onChange,
  idPrefix = 'option',
}: {
  options: PlacementOption[];
  chosen: Record<string, string>;
  /** Called once per setting that changes — a pick can blank another one it rules out. */
  onChange: (key: string, value: string) => void;
  /** Keeps the field ids apart when two of these are mounted at once. */
  idPrefix?: string;
}) {
  const { t } = useTranslation();

  function pick(key: string, value: string) {
    for (const [changed, next] of Object.entries(choose(options, chosen, key, value))) {
      onChange(changed, next);
    }
  }

  return (
    <>
      {options.map((option) => {
        const id = `${idPrefix}-${option.key}`;
        const label = t(`directory.option.${option.key}`, { defaultValue: option.key });
        const values = offeredValues(options, chosen, option);
        // Narrowed to nothing: the other setting rules every value out, and blank — the tool's
        // own default — is the only thing left. Said, rather than shown as an empty list.
        const nothingLeft = values.length === 0;
        return (
          <div key={option.key}>
            <label htmlFor={id} className="block text-[13px] font-medium text-[#2A2318] mb-1">
              {label}
            </label>
            {isClosed(option) || nothingLeft ? (
              <Dropdown
                id={id}
                value={chosen[option.key] ?? ''}
                onChange={(value) => pick(option.key, value)}
                disabled={nothingLeft}
                // Blank stays a real choice: FR-007k says an unset setting means the tool's
                // own default, so the person must be able to get back to it.
                items={[
                  { value: '', label: t('directory.optionDefault') },
                  ...values.map((value) => ({ value, label: labelOf(option, value) })),
                ]}
              />
            ) : (
              // A list the tool did not claim is everything — examples from its help, or the
              // models it lists for this account while still running others — so this is a
              // box with the whole list a click away, and room to type something else.
              <SuggestBox
                id={id}
                value={chosen[option.key] ?? ''}
                onChange={(value) => pick(option.key, value)}
                blankLabel={t('directory.optionDefault')}
                suggestions={values.map((value) => ({
                  value,
                  label: option.labels?.[value],
                }))}
              />
            )}
            {nothingLeft && (
              <p className="mt-1 text-[11px] text-[#6B5E4E]">
                {t('directory.optionRuledOut')}
              </p>
            )}
          </div>
        );
      })}
      {/* Said once for the group, not once per field. Where the list comes from is one fact
          about all of them, and repeating it under each turns the shorter answer — what the
          field actually is — into the thing the eye skips. */}
      {options.length > 0 && (
        <p className="text-[11px] text-[#A89880]">{t('directory.optionHint')}</p>
      )}
    </>
  );
}
