// `/skills/:id` — one skill opened in the library.
//
// The library and the open skill are one screen in the Đài quan sát design (list on the left,
// files on the right), so this route renders that screen; `Skills` reads the id off the address
// and, on a narrow screen, shows the skill on its own with a way back to the list.
//
// A skill's files are shown read-only: the server has no call that changes them after the
// skill is created, so there is nothing an edit here could be saved to.
import Skills from './Skills';

export default function SkillEditor() {
  return <Skills />;
}
