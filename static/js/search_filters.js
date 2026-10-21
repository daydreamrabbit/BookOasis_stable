export function filteredSearchUrl(action, args) {
  if (!['general','adult'].includes(args.type)) return null;
  if (!args.advanced && !(args.genres?.length || args.tags?.length)) return null;
  const filters = args.advanced ? {...args.advanced} : {
    series: args.search || '', genre: args.genres || [], tags: args.tags || [],
    genre_mode: args.filterMode || 'and', tags_mode: args.filterMode || 'and'
  };
  const params = new URLSearchParams({type:args.type, library_id:args.advanced ? 'all' : (args.libraryId || 'all'), filters:JSON.stringify(filters)});
  params.set('read_filter', args.readFilter || '');
  if (args.includeHasMetadata) params.set('include_has_metadata','1');
  for (const key of ['page','limit','sort','char','start_id','end_id','start_library_id','end_library_id'])
    if (args[key] !== undefined) params.set(key,String(args[key]));
  return '/api/media/advanced-search/' + action + '?' + params;
}
