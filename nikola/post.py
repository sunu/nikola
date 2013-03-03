# -*- coding: utf-8 -*-
# Copyright (c) 2012 Roberto Alsina y otros.

# Permission is hereby granted, free of charge, to any
# person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the
# Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the
# Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice
# shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
# KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS
# OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from __future__ import unicode_literals, print_function

import codecs
import os
import re
import sys
import string

import unidecode
import lxml.html

from .utils import to_datetime, slugify

__all__ = ['Post']

TEASER_REGEXP = re.compile('<!--\s*TEASER_END(:(.+))?\s*-->', re.IGNORECASE)


class Post(object):

    """Represents a blog post or web page."""

    def __init__(
        self, source_path, cache_folder, destination, use_in_feeds,
        translations, default_lang, base_url, messages, template_name,
        file_metadata_regexp=None, tzinfo=None, url_pattern=None
    ):
        """Initialize post.

        The source path is the .txt post file. From it we calculate
        the meta file, as well as any translations available, and
        the .html fragment file path.
        """
        self.translated_to = set([default_lang])
        self.tags = ''
        self.date = None
        self.prev_post = None
        self.next_post = None
        self.base_url = base_url
        self.is_draft = False
        self.is_mathjax = False
        self.source_path = source_path  # posts/blah.txt
        self.post_name = os.path.splitext(source_path)[0]  # posts/blah
        # cache/posts/blah.html
        self.base_path = os.path.join(cache_folder, self.post_name + ".html")
        self.metadata_path = self.post_name + ".meta"  # posts/blah.meta
        self.folder = destination
        self.translations = translations
        self.default_lang = default_lang
        self.messages = messages
        self.template_name = template_name
        self.url_pattern = url_pattern
        self.meta = get_meta(self, file_metadata_regexp)

        default_title = self.meta.get('title', '')
        default_pagename = self.meta.get('slug', '')
        default_description = self.meta.get('description', '')

        for k, v in self.meta.items():
            if k not in ['title', 'slug', 'description']:
                if sys.version_info[0] == 2:
                    setattr(self, unidecode.unidecode(unicode(k)), v)  # NOQA
                else:
                    setattr(self, k, v)

        if not default_title or not default_pagename or not self.date:
            raise OSError("You must set a title (found '{0}'), a slug (found "
                          "'{1}') and a date (found '{2}')! [in file "
                          "{3}]".format(default_title, default_pagename,
                                        self.date, source_path))

        # If timezone is set, build localized datetime.
        self.date = to_datetime(self.date, tzinfo)
        self.tags = [x.strip() for x in self.tags.split(',')]
        self.tags = [_f for _f in self.tags if _f]

        # While draft comes from the tags, it's not really a tag
        self.use_in_feeds = use_in_feeds and "draft" not in self.tags
        self.is_draft = 'draft' in self.tags
        self.tags = [t for t in self.tags if t != 'draft']

        # If mathjax is a tag, then enable mathjax rendering support
        self.is_mathjax = 'mathjax' in self.tags

        self.pagenames = {}
        self.titles = {}
        self.descriptions = {}

        # Load internationalized metadata
        for lang in translations:
            if lang == default_lang:
                self.titles[lang] = default_title
                self.pagenames[lang] = default_pagename
                self.descriptions[lang] = default_description
            else:
                if os.path.isfile(self.source_path + "." + lang):
                    self.translated_to.add(lang)

                meta = self.meta.copy()
                meta.update(get_meta(self.source_path, file_metadata_regexp, lang))

                # FIXME this only gets three pieces of metadata from the i18n files
                self.titles[lang] = meta['title']
                self.pagenames[lang] = meta['slug']
                self.descriptions[lang] = meta['description']

    def title(self, lang):
        """Return localized title."""
        return self.titles[lang]

    def description(self, lang):
        """Return localized description."""
        return self.descriptions[lang]

    def deps(self, lang):
        """Return a list of dependencies to build this post's page."""
        deps = [self.base_path]
        if lang != self.default_lang:
            deps += [self.base_path + "." + lang]
        deps += self.fragment_deps(lang)
        return deps

    def fragment_deps(self, lang):
        """Return a list of dependencies to build this post's fragment."""
        deps = [self.source_path]
        if os.path.isfile(self.metadata_path):
            deps.append(self.metadata_path)
        if lang != self.default_lang:
            lang_deps = list(filter(os.path.exists, [x + "." + lang for x in
                                                     deps]))
            deps += lang_deps
        return deps

    def is_translation_available(self, lang):
        """Return true if the translation actually exists."""
        return lang in self.translated_to

    def _translated_file_path(self, lang):
        """Return path to the translation's file, or to the original."""
        file_name = self.base_path
        if lang != self.default_lang:
            file_name_lang = '.'.join((file_name, lang))
            if os.path.exists(file_name_lang):
                file_name = file_name_lang
        return file_name

    def text(self, lang, teaser_only=False, strip_html=False):
        """Read the post file for that language and return its contents"""
        file_name = self._translated_file_path(lang)

        with codecs.open(file_name, "r", "utf8") as post_file:
            data = post_file.read()

        if data:
            data = lxml.html.make_links_absolute(data, self.permalink(lang=lang))
        if data and teaser_only:
            e = lxml.html.fromstring(data)
            teaser = []
            teaser_str = self.messages[lang]["Read more"] + '...'
            flag = False
            for elem in e:
                elem_string = lxml.html.tostring(elem).decode('utf8')
                match = TEASER_REGEXP.match(elem_string)
                if match:
                    flag = True
                    if match.group(2):
                        teaser_str = match.group(2)
                    break
                teaser.append(elem_string)
            if flag:
                teaser.append('<p><a href="{0}">{1}</a></p>'.format(
                    self.permalink(lang), teaser_str))
            data = ''.join(teaser)

        if data and strip_html:
            content = lxml.html.fromstring(data)
            data = content.text_content().strip()  # No whitespace wanted.

        return data

    def destination_path(self, lang, extension='.html'):
        if self.url_pattern:
            path = self.url_pattern.format(self,
                                           language=lang,
                                           language_location=self.translations[lang],
                                           slug=self.pagenames[lang],extension=extension)
        else:
            path = os.path.join(self.translations[lang],
                                self.folder,
                                self.pagenames[lang] + extension)

        return path

    def permalink(self, lang=None, absolute=False, extension='.html'):
        if lang is None:
            lang = self.default_lang
        pieces = list(os.path.split(self.translations[lang]))
        pieces += list(os.path.split(self.folder))
        pieces += [self.pagenames[lang] + extension]
        pieces = [_f for _f in pieces if _f and _f != '.']
        if absolute:
            pieces = [self.base_url] + pieces
        else:
            pieces = [""] + pieces
        link = "/".join(pieces)
        return link

    def source_ext(self):
        return os.path.splitext(self.source_path)[1]

# Code that fetches metadata from different places


def re_meta(line, match=None):
    """re.compile for meta"""
    if match:
        reStr = re.compile('^\.\. {0}: (.*)'.format(re.escape(match)))
    else:
        reStr = re.compile('^\.\. (.*?): (.*)')
    result = reStr.findall(line.strip())
    if match and result:
        return (match, result[0])
    elif not match and result:
        return (result[0][0], result[0][1].strip())
    else:
        return (None,)


def _get_metadata_from_filename_by_regex(filename, metadata_regexp):
    """
    Tries to ried the metadata from the filename based on the given re.
    This requires to use symbolic group names in the pattern.

    The part to read the metadata from the filename based on a regular
    expression is taken from Pelican - pelican/readers.py
    """
    match = re.match(metadata_regexp, filename)
    meta = {}

    if match:
        # .items() for py3k compat.
        for key, value in match.groupdict().items():
            meta[key.lower()] = value  # metadata must be lowercase

    return meta


def get_metadata_from_file(source_path):
    """Extracts metadata from the file itself, by parsing contents."""
    try:
        with codecs.open(source_path, "r", "utf8") as meta_file:
            meta_data = [x.strip() for x in meta_file.readlines()]
        return _get_metadata_from_file(meta_data)
    except Exception:  # The file may not exist, for multilingual sites
        return {}


def _get_metadata_from_file(meta_data):
    """Parse file contents and obtain metadata.

    >>> g = _get_metadata_from_file
    >>> list(g([]).values())
    []
    >>> str(g(["FooBar","======"])["title"])
    'FooBar'
    >>> str(g(["#FooBar"])["title"])
    'FooBar'
    >>> str(g([".. title: FooBar"])["title"])
    'FooBar'
    >>> 'title' in g(["",".. title: FooBar"])
    False

    """
    meta = {}

    re_md_title = re.compile(r'^{0}([^{0}].*)'.format(re.escape('#')))
    # Assuming rst titles are going to be at least 4 chars long
    # otherwise this detects things like ''' wich breaks other markups.
    re_rst_title = re.compile(r'^([{0}]{{4,}})'.format(re.escape(
        string.punctuation)))

    for i, line in enumerate(meta_data):
        if not line:
            break
        if 'title' not in meta:
            match = re_meta(line, 'title')
            if match[0]:
                meta['title'] = match[1]
        if 'title' not in meta:
            if re_rst_title.findall(line) and i > 0:
                meta['title'] = meta_data[i - 1].strip()
        if 'title' not in meta:
            if re_md_title.findall(line):
                meta['title'] = re_md_title.findall(line)[0]

        match = re_meta(line)
        if match[0]:
            meta[match[0]] = match[1]

    return meta


def get_metadata_from_meta_file(path, lang=None):
    """Takes a post path, and gets data from a matching .meta file."""
    meta_path = os.path.splitext(path)[0] + '.meta'
    if lang:
        meta_path += '.' + lang
    if os.path.isfile(meta_path):
        with codecs.open(meta_path, "r", "utf8") as meta_file:
            meta_data = meta_file.readlines()
        while len(meta_data) < 6:
            meta_data.append("")
        (title, slug, date, tags, link, description) = [
            x.strip() for x in meta_data][:6]

        meta = {}

        if title:
            meta['title'] = title
        if slug:
            meta['slug'] = slug
        if date:
            meta['date'] = date
        if tags:
            meta['tags'] = tags
        if link:
            meta['link'] = link
        if description:
            meta['description'] = description

        return meta
    else:
        return {}


def get_meta(post, file_metadata_regexp=None, lang=None):
    """Get post's meta from source.

    If ``file_metadata_regexp`` is given it will be tried to read
    metadata from the filename.
    If any metadata is then found inside the file the metadata from the
    file will override previous findings.
    """
    meta = {}

    meta.update(get_metadata_from_meta_file(post.metadata_path, lang))

    if meta:
        return meta

    if file_metadata_regexp is not None:
        meta.update(_get_metadata_from_filename_by_regex(post.source_path,
                                                         file_metadata_regexp))

    meta.update(get_metadata_from_file(post.source_path))

    if 'slug' not in meta:
        # If no slug is found in the metadata use the filename
        meta['slug'] = slugify(os.path.splitext(
            os.path.basename(post.source_path))[0])

    if 'title' not in meta:
        # If no title is found, use the filename without extension
        meta['title'] = os.path.splitext(os.path.basename(post.source_path))[0]

    return meta
