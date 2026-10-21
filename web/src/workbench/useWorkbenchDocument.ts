import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../lib/api";
import type { Example, Language, Script, Snippet } from "../types";
import { initialDocument } from "./types";
import type { DocumentState } from "./types";

interface Options {
  user: string;
  refresh: () => Promise<void>;
  notify: (message: string) => void;
}

export default function useWorkbenchDocument({
  user,
  refresh,
  notify,
}: Options) {
  const [document, setDocument] = useState<DocumentState>(() =>
    initialDocument("javascript"),
  );
  const drafts = useRef<Partial<Record<Language, DocumentState>>>({});

  useEffect(() => {
    if (!document.dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [document.dirty]);

  const onCode = useCallback(
    (code: string) =>
      setDocument((previous) =>
        previous.code === code ? previous : { ...previous, code, dirty: true },
      ),
    [],
  );

  const changeLanguage = (language: Language) => {
    drafts.current[document.language] = document;
    setDocument(drafts.current[language] || initialDocument(language));
  };

  const createScript = () => {
    drafts.current[document.language] = document;
    setDocument({
      ...initialDocument(document.language),
      title: "未命名脚本",
    });
  };

  const loadScript = (script: Script) => {
    drafts.current[document.language] = document;
    setDocument({
      id: script.user_id === user ? script.id : null,
      title: script.title,
      code: script.code,
      language: script.language || "python",
      shared: script.user_id === user && script.shared,
      dirty: false,
    });
  };

  const loadExample = (example: Example) => {
    drafts.current[document.language] = document;
    setDocument({
      id: null,
      title: example.name,
      code: example.code,
      language: example.language || "python",
      shared: false,
      dirty: false,
    });
  };

  const insertSnippet = (snippet: Snippet) => {
    drafts.current[document.language] = document;
    const base =
      snippet.language === document.language
        ? document
        : drafts.current[snippet.language] || initialDocument(snippet.language);
    setDocument({
      ...base,
      code: base.code + "\n" + snippet.code + "\n",
      dirty: true,
    });
  };

  const updateTitle = (title: string) =>
    setDocument((previous) => ({ ...previous, title, dirty: true }));

  const updateShared = (shared: boolean) =>
    setDocument((previous) => ({ ...previous, shared, dirty: true }));

  const save = async (onSaved: (shared: boolean) => void) => {
    try {
      const result = await api<{ id?: string }>(
        document.id
          ? "/workbench/scripts/" + document.id
          : "/workbench/scripts",
        document.id ? "PUT" : "POST",
        { ...document },
      );
      setDocument((previous) => ({
        ...previous,
        id: result.id || previous.id,
        dirty: previous.code !== document.code,
      }));
      onSaved(document.shared);
      await refresh();
    } catch (error) {
      notify(errorMessage(error));
    }
  };

  return {
    document,
    setDocument,
    onCode,
    changeLanguage,
    createScript,
    loadScript,
    loadExample,
    insertSnippet,
    updateTitle,
    updateShared,
    save,
  };
}
