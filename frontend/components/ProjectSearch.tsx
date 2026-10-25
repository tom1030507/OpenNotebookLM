'use client';

import { useState, type FormEvent } from 'react';
import api, { type ProjectSearchResponse } from '@/lib/api';

interface ProjectSearchProps {
  onOpenResult: (projectId: string, documentId: string) => void;
}

export default function ProjectSearch({ onOpenResult }: ProjectSearchProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ProjectSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const search = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const searchText = query.trim();
    if (!searchText || loading) return;

    setLoading(true);
    setError('');
    setResults(null);
    try {
      const response = await api.searchProjects(searchText);
      setResults(response);
    } catch (searchError) {
      setError(searchError instanceof Error ? searchError.message : 'Search failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section aria-label="Search all projects" className="mb-3 rounded-md border border-[var(--input)] p-2">
      <form onSubmit={search} className="flex gap-1.5">
        <label className="sr-only" htmlFor="project-search-query">Search across projects</label>
        <input
          id="project-search-query"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search across projects"
          disabled={loading}
          className="min-w-0 flex-1 h-8 px-2 bg-[var(--card)] border border-[var(--input)] rounded-md text-xs focus:outline-none focus:ring-2 focus:ring-[var(--ring)] disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="h-8 px-2 rounded-md bg-[var(--primary)] text-[var(--primary-foreground)] text-xs disabled:opacity-50"
        >
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {loading && <p role="status" className="mt-2 text-xs text-[var(--muted-foreground)]">Searching projects...</p>}
      {error && <p role="alert" className="mt-2 text-xs text-[var(--error)]">{error}</p>}
      {results && (
        results.projects.length > 0 ? (
          <div aria-label="Project search results" className="mt-2 max-h-64 space-y-2 overflow-y-auto">
            {results.projects.map((project) => (
              <section key={project.project_id} aria-label={project.project_name}>
                <h3 className="text-xs font-semibold text-[var(--muted-foreground)]">
                  {project.project_name}
                </h3>
                {project.documents.map((document) => (
                  <div key={document.document_id} className="mt-1">
                    <h4 className="truncate text-xs font-medium" title={document.title}>
                      {document.title}
                    </h4>
                    {document.passages.map((passage) => (
                      <button
                        key={passage.chunk_id}
                        type="button"
                        onClick={() => onOpenResult(project.project_id, document.document_id)}
                        aria-label={`Open ${document.title} in ${project.project_name}: ${passage.text.slice(0, 80)}`}
                        className="mt-1 w-full rounded p-1.5 text-left text-xs hover:bg-[var(--muted)]"
                      >
                        <span className="line-clamp-3">{passage.text}</span>
                        {(passage.section || passage.page_num !== null) && (
                          <span className="mt-1 block text-[var(--muted-foreground)]">
                            {[passage.section, passage.page_num !== null ? `Page ${passage.page_num}` : null]
                              .filter(Boolean)
                              .join(' · ')}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                ))}
              </section>
            ))}
          </div>
        ) : (
          <p role="status" className="mt-2 text-xs text-[var(--muted-foreground)]">No passages found.</p>
        )
      )}
    </section>
  );
}
