import { useEffect, useRef } from "react";
import { Compartment, EditorState } from "@codemirror/state";
import {
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import {
  bracketMatching,
  HighlightStyle,
  indentOnInput,
  syntaxHighlighting,
} from "@codemirror/language";
import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import { json } from "@codemirror/lang-json";
import { tags } from "@lezer/highlight";
const highlights = HighlightStyle.define([
  { tag: tags.comment, color: "#81988e" },
  { tag: tags.keyword, color: "#8b65aa" },
  { tag: tags.string, color: "#56866b" },
  { tag: tags.number, color: "#b87e4d" },
  { tag: tags.function(tags.variableName), color: "#537c96" },
  { tag: tags.operator, color: "#6e8188" },
]);
import type { Language } from "../types";
interface Props {
  value: string;
  language: Language | "json";
  onChange: (code: string) => void;
  onCursor?: (line: number, column: number) => void;
  onRun?: () => void;
  onSave?: () => void;
  reveal?: { line: number; column: number; sequence: number };
}
const languageExtension = (language: Props["language"]) =>
  language === "python"
    ? python()
    : language === "json"
      ? json()
      : javascript();
export default function CodeEditor(props: Props) {
  const target = useRef<HTMLDivElement>(null),
    editor = useRef<EditorView | null>(null),
    config = useRef(new Compartment()),
    latest = useRef(props);
  latest.current = props;
  useEffect(() => {
    if (!target.current) return;
    const view = new EditorView({
      parent: target.current,
      state: EditorState.create({
        doc: latest.current.value,
        extensions: [
          lineNumbers(),
          history(),
          highlightActiveLine(),
          highlightActiveLineGutter(),
          indentOnInput(),
          bracketMatching(),
          syntaxHighlighting(highlights),
          EditorView.lineWrapping,
          config.current.of(languageExtension(latest.current.language)),
          keymap.of([
            {
              key: "Mod-Enter",
              run: () => {
                latest.current.onRun?.();
                return true;
              },
            },
            {
              key: "Mod-s",
              run: () => {
                latest.current.onSave?.();
                return true;
              },
            },
            indentWithTab,
            ...defaultKeymap,
            ...historyKeymap,
          ]),
          EditorView.updateListener.of((update) => {
            if (update.docChanged)
              latest.current.onChange(update.state.doc.toString());
            if (update.docChanged || update.selectionSet) {
              const position = update.state.selection.main.head;
              const line = update.state.doc.lineAt(position);
              latest.current.onCursor?.(line.number, position - line.from + 1);
            }
          }),
          EditorView.contentAttributes.of({
            "aria-label": "脚本代码编辑器",
            spellcheck: "false",
          }),
        ],
      }),
    });
    editor.current = view;
    return () => {
      view.destroy();
      editor.current = null;
    };
  }, []);
  useEffect(() => {
    const view = editor.current;
    if (view && view.state.doc.toString() !== props.value)
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: props.value },
      });
  }, [props.value]);
  useEffect(() => {
    editor.current?.dispatch({
      effects: config.current.reconfigure(languageExtension(props.language)),
    });
  }, [props.language]);
  useEffect(() => {
    const view = editor.current,
      location = props.reveal;
    if (!view || !location) return;
    const line = view.state.doc.line(
      Math.max(1, Math.min(location.line, view.state.doc.lines)),
    );
    const position = Math.min(
      line.to,
      line.from + Math.max(0, location.column - 1),
    );
    view.dispatch({
      selection: { anchor: position },
      effects: EditorView.scrollIntoView(position, { y: "center" }),
    });
    view.focus();
  }, [props.reveal]);
  return <div ref={target} className="code-editor" />;
}
