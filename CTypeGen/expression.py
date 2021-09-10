# Copyright (c) 2021 Arista Networks, Inc.  All rights reserved.
# Arista Networks, Inc. Confidential and Proprietary.

from __future__ import absolute_import, division, print_function
import sys
import ast
import token
import tokenize

PY3 = sys.version_info.major >= 3

# make python2's tokenize.tokenize behave more like python3
if PY3:
   TokenInfo = tokenize.TokenInfo # for python2: pylint: disable=no-member
else:
   class TokenInfo(object):
      def __init__( self, tup ):
         self.type, self.string, self.start, self.end, self.line = tup
      def __repr__( self ):
         return ( "TokenInfo(type=%d (%s), string='%s', start=%s, end=%s, line='%s'"
               % (self.type, token.tok_name[self.type], self.string, self.start,
                        self.end, self.line ) )

# Act like readline for a fixed string.
class Reader( object ):
   def __init__( self, text ):
      if PY3 and isinstance( text, str ):
         self.text = text.encode("utf-8")
      else:
         self.text = text

   def __call__( self ):
      if self.text:
         rv = self.text
         self.text = None
         return rv
      return b""

def getTokens(b):
   if not PY3:
      alltoks = []
      def eat(a, b, c, d, e):
         alltoks.append(TokenInfo((a, b, c, d, e)))
      tokenize.tokenize(Reader(b), eat)
      return alltoks
   else:
      return tokenize.tokenize(Reader(b))

def clean( input_ ):
   ''' If "input_" is a usable expression, convert it into valid python,
   returning a 2-tuple contining the conversion, and a list of identifiers that
   are used in the string. Otherwise return ( None, None ) '''

   # the names of identifiers used in the expression - will return this
   # to caller.
   name_list = []

   # Step one - lexical cleanup.
   try:
      kill_suffixes = set( [ "UL", "U", "ULL", "L", "LL" ] )
      output = ''
      prev_tok = None
      for tok in getTokens(input_):
         # py2 has no ENCODING field; disable lint error. pylint: disable=no-member
         if tok.type == token.INDENT or PY3 and tok.type == token.ENCODING:
            continue
         # pylint: enable=no-member

         if prev_tok:
            # splice in any whitespace that was skipped over into the output.
            output += input_[ prev_tok.end[ 1 ] : tok.start[ 1 ] ]

         # If the token for a number ends with "L", remove it.
         if tok.type == token.NUMBER and tok.string[-1].upper() == 'L':
            output += tok.string[:-1]

         # If the token is a single character string, then convert it to the literal
         # character ordinal. C characters a numeric types, so treat as a python
         # number.
         elif tok.type == token.STRING and tok.string[0] == "'" and \
                              len( tok.string ) == 3 and tok.string[2] == "'":
            output += str(ord(tok.string[1]))

         # Convert old style octal numbers ("0123") to new style ("0o123")
         elif tok.type == token.NUMBER and len(tok.string) >= 2 and \
               tok.string[0] == '0' and tok.string[1].upper() != 'X':
            output += "0o%s" % tok.string[1:]

         # if the previous token was a number, and now we have a name like
         # "UL", just drop this token - it's a precision suffix that python
         # doesn't need.
         elif prev_tok is not None and prev_tok.type == token.NUMBER and \
                  tok.type == token.NAME and tok.string.upper() in kill_suffixes:
            pass
         else: # emit token unmodified.
            if tok.type == token.NAME:
               name_list.append( tok.string )
            output += tok.string
         prev_tok = tok
   except tokenize.TokenError:
      return None, None

   # Step 2 - see if we have a valid python expression.
   try:
      tree = ast.parse( output )

      # We only want things that parse as a single expression.
      if len(tree.body) != 1 or not isinstance( tree.body[0], ast.Expr ):
         return None, None

      # Many system headers include macros for brace-initializers. They look
      # like sets to python, and when they nest, it causes a problem as they
      # are not hashable. The definitions are of no use to python anyhow, so
      # just discard them.
      if isinstance( tree.body[0].value, ast.Set ):
         return None, None

      return output, name_list

   except SyntaxError:
      pass
   return None, None
