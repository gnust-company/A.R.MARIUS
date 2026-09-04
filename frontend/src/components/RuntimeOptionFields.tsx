// What a person may set on one agent, drawn from what the place it works at answered
// (FR-007k, FR-017). Nothing here is keyed on which CLI it is — the list arrives as data,
// and a place that offered nothing simply draws nothing.
//
// One component because there are two screens: choosing settings for a new agent, and
// changing them on one that exists. Two copies of this would be two renderings of the same
// data, and the one that drifts is the one nobody is looking at.
import { useTranslation } from 'react-i18next';
import type { PlacementOption } from '@/store/appStore';
import { cn } from '@/lib/utils';

const FIELD = cn(
  'w-full px-4 py-2.5 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
  'placeholder:text-[#A89880]',
  'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
  'transition-all'
);

export default function RuntimeOptionFields({
  options,
  chosen,
  onChange,
  idPrefix = 'option',
}: {
  options: PlacementOption[];
  chosen: Record<string, string>;
  onChange: (key: string, value: string) => void;
  /** Keeps the `<datalist>` ids apart when two of these are mounted at once. */
  idPrefix?: string;
}) {
  const { t } = useTranslation();
  return (
    <>
      {options.map((option) => (
        <div key={option.key}>
          <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
            {t(`directory.option.${option.key}`, { defaultValue: option.key })}
          </label>
          {option.source === 'tool_examples' ? (
            // The tool named a few by way of example and did not claim they are all, so this
            // is a box with suggestions beside it. Offering them as the only three would
            // refuse a real model the day a fourth ships.
            <>
              <input
                type="text"
                list={`${idPrefix}-${option.key}`}
                value={chosen[option.key] ?? ''}
                onChange={(e) => onChange(option.key, e.target.value)}
                placeholder={t('directory.optionDefault')}
                className={FIELD}
              />
              <datalist id={`${idPrefix}-${option.key}`}>
                {option.values.map((value) => (
                  <option key={value} value={value} />
                ))}
              </datalist>
            </>
          ) : (
            <select
              value={chosen[option.key] ?? ''}
              onChange={(e) => onChange(option.key, e.target.value)}
              className={FIELD}
            >
              {/* Blank stays a real choice: FR-007k says an unset setting means the tool's
                  own default, so the person must be able to get back to it. */}
              <option value="">{t('directory.optionDefault')}</option>
              {option.values.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          )}
        </div>
      ))}
      {/* Said once for the group, not once per field. Where the list comes from is one fact
          about all of them, and repeating it under each turns the shorter answer — what the
          field actually is — into the thing the eye skips. */}
      {options.length > 0 && (
        <p className="text-[11px] text-[#A89880]">{t('directory.optionHint')}</p>
      )}
    </>
  );
}
