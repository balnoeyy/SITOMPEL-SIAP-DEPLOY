import sys
from copy import copy


if sys.version_info >= (3, 14):
    from django.template.context import BaseContext, Context

    def _copy_base_context(self):
        duplicate = self.__class__.__new__(self.__class__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    def _copy_context(self):
        duplicate = _copy_base_context(self)
        duplicate.render_context = copy(self.render_context)
        return duplicate

    BaseContext.__copy__ = _copy_base_context
    Context.__copy__ = _copy_context
