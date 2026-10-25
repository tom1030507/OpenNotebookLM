'use client';

import React, { useEffect, useState } from 'react';
import { MessageSquare } from 'lucide-react';
import api from '@/lib/api';
import useStore from '@/store/useStore';

interface QuestionListProps {
  questions: string[];
  disabled?: boolean;
  onAsk: (question: string) => void;
}

function QuestionList({ questions, disabled, onAsk }: QuestionListProps) {
  return (
    <ul className="flex flex-col gap-2 text-left">
      {questions.map((question) => (
        <li key={question}>
          <button
            type="button"
            onClick={() => onAsk(question)}
            disabled={disabled}
            className="w-full flex items-start gap-2 px-3 py-2 text-left text-sm bg-[var(--card)] border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] disabled:opacity-50 disabled:cursor-not-allowed transition-base"
          >
            <MessageSquare className="w-4 h-4 mt-0.5 flex-shrink-0 text-[var(--muted-foreground)]" />
            <span>{question}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

interface ProjectOverviewProps {
  projectId: string;
  /** Changes whenever the set of ready sources does, which may regenerate the overview. */
  readySourceKey: string;
  outputLanguageRevision?: number;
  disabled?: boolean;
  onAsk: (question: string) => void;
}

/** The generated overview and starter questions; renders nothing until there are some. */
export function ProjectOverview({
  projectId,
  readySourceKey,
  outputLanguageRevision = 0,
  disabled,
  onAsk,
}: ProjectOverviewProps) {
  const [overview, setOverview] = useState<{ text: string | null; questions: string[] }>({
    text: null,
    questions: [],
  });

  useEffect(() => {
    let current = true;
    setOverview({ text: null, questions: [] });
    api.fetchProjectOverview(projectId).then((result) => {
      if (!current) return;
      setOverview({ text: result.overview, questions: result.questions });
      // The server may have replaced a placeholder name with a generated title.
      useStore.setState((state) => ({
        projects: state.projects.map((project) => (
          project.id === projectId ? { ...project, name: result.project_name } : project
        )),
        currentProject: state.currentProject?.id === projectId
          ? { ...state.currentProject, name: result.project_name }
          : state.currentProject,
      }));
    }).catch((error) => {
      // Suggestions are optional; the empty state stays usable without them.
      console.error('Failed to load project overview:', error);
    });
    return () => {
      current = false;
    };
  }, [projectId, readySourceKey, outputLanguageRevision]);

  if (!overview.text && overview.questions.length === 0) return null;

  return (
    <div data-testid="project-overview" className="max-w-2xl mx-auto mb-8 text-left">
      {overview.text && (
        <p className="text-sm leading-relaxed mb-4">{overview.text}</p>
      )}
      {overview.questions.length > 0 && (
        <QuestionList questions={overview.questions} disabled={disabled} onAsk={onAsk} />
      )}
    </div>
  );
}

interface FollowUpQuestionsProps {
  conversationId: string;
  /** The answer the questions follow; a new answer fetches new ones. */
  messageId: string;
  disabled?: boolean;
  onAsk: (question: string) => void;
}

/** Two follow-up questions under the latest answer; renders nothing without a model. */
export function FollowUpQuestions({
  conversationId,
  messageId,
  disabled,
  onAsk,
}: FollowUpQuestionsProps) {
  const [questions, setQuestions] = useState<string[]>([]);

  useEffect(() => {
    let current = true;
    setQuestions([]);
    api.fetchFollowUpQuestions(conversationId).then((result) => {
      if (current) setQuestions(result);
    }).catch((error) => {
      console.error('Failed to load follow-up questions:', error);
    });
    return () => {
      current = false;
    };
  }, [conversationId, messageId]);

  if (questions.length === 0) return null;

  return (
    <div data-testid="follow-up-questions" className="pl-11">
      <p className="text-xs text-[var(--muted-foreground)] mb-2">Follow-up questions</p>
      <QuestionList questions={questions} disabled={disabled} onAsk={onAsk} />
    </div>
  );
}
