from django.utils.encoding import smart_unicode
from django.db.models.fields import BLANK_CHOICE_DASH
from django.db.models.sql.constants import LOOKUP_SEP

class BoundRelatedObject(object):
    def __init__(self, related_object, field_mapping, original):
        self.relation = related_object
        self.field_mappings = field_mapping[related_object.name]

    def template_name(self):
        raise NotImplementedError

    def __repr__(self):
        return repr(self.__dict__)

class RelatedObject(object):
    def __init__(self, parent_model, model, field):
        self.parent_model = parent_model
        self.model = model
        self.opts = model._meta
        self.field = field
        self.name = '%s:%s' % (self.opts.app_label, self.opts.module_name)
        self.var_name = self.opts.object_name.lower()

    def get_choices(self, include_blank=True, blank_choice=BLANK_CHOICE_DASH,
                    limit_to_currently_related=False):
        """Returns choices with a default blank choices included, for use
        as SelectField choices for this field.

        Analogue of django.db.models.fields.Field.get_choices, provided
        initially for utilisation by RelatedFieldListFilter.
        """
        first_choice = include_blank and blank_choice or []
        queryset = self.model._default_manager.all()
        if limit_to_currently_related:
            queryset = queryset.complex_filter(
                {'%s__isnull' % self.parent_model._meta.module_name: False})
        lst = [(x._get_pk_val(), smart_unicode(x)) for x in queryset]
        return first_choice + lst

    def get_db_prep_lookup(self, lookup_type, value, connection, prepared=False):
        # Defer to the actual field definition for db prep
        return self.field.get_db_prep_lookup(lookup_type, value,
                        connection=connection, prepared=prepared)

    def editable_fields(self):
        "Get the fields in this class that should be edited inline."
        return [f for f in self.opts.fields + self.opts.many_to_many if f.editable and f != self.field]

    def __repr__(self):
        return "<RelatedObject: %s related to %s>" % (self.name, self.field.name)

    def bind(self, field_mapping, original, bound_related_object_class=BoundRelatedObject):
        return bound_related_object_class(self, field_mapping, original)

    def get_accessor_name(self):
        # This method encapsulates the logic that decides what name to give an
        # accessor descriptor that retrieves related many-to-one or
        # many-to-many objects. It uses the lower-cased object_name + "_set",
        # but this can be overridden with the "related_name" option.
        if self.field.rel.multiple:
            # If this is a symmetrical m2m relation on self, there is no reverse accessor.
            if getattr(self.field.rel, 'symmetrical', False) and self.model == self.parent_model:
                return None
            return self.field.rel.related_name or (self.opts.object_name.lower() + '_set')
        else:
            return self.field.rel.related_name or (self.opts.object_name.lower())

    def get_cache_name(self):
        return "_%s_cache" % self.get_accessor_name()

# Not knowing a better place for this, I just planted R here.
# Feel free to move this to a better place or remove this comment.
class R(object):
    """
    A class used for passing options to .prefetch_related. Note that instances
    of this class should be considered immutable.
    """

    # For R-objects, we have two different internal lookup paths:
    #   - lookup: This is the related object attribute name
    #   - lookup_refpath: This is to be used when this R-object is referenced
    #     in chained prefetches.
    # Check out the source of R-objects to see what is happening there.
    #
    # The difference is needed, because when we chain R-objects with to_attr
    # defined, the lookup_path (how we got here) and lookup_refpath (how to
    # get forward from here) will be different. For example:
    # R('foo', to_attr='foolst') -> lookup_path = foo, that is we are going
    # to prefetch through relation foo.
    #
    # If there would be another qs produced by R, the lookup_refpath would
    # need to be 'foolst__nextpart'. Otherwise we can't distinguish between
    # two different prefetch_related lookups to 'foo' (perhaps with custom
    # querysets).
    #
    # Luckily the user does not need to know anything about this.

    def __init__(self, lookup, to_attr=None, qs=None):
        if qs is not None and not to_attr:
            raise ValueError('When custom qs is defined, to_attr '
                             'must also be defined')
        self.lookup = lookup
        self.to_attr = to_attr
        self.qs = qs

    def _new_prefixed(self, prefix):
        """
        _new_internal is to be used when prefetches are chained internally.
        The returned R-object is identical to self, except lookup_path
        is prefixed with prefix.
        """
        new_lookup = prefix + LOOKUP_SEP + self.lookup
        return R(new_lookup, to_attr=self.to_attr, qs=self.qs)

    def __unicode__(self):
        return ("lookup: %s, to_attr: %s, qs: %s" %
            (self.lookup, self.to_attr or None, self.qs))

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, unicode(self))

    def __eq__(self, other):
        if isinstance(other, R):
            return self.lookup_refpath == other.lookup_refpath
        return False

    def _lookup_refpath(self):
        if self.to_attr is None:
            return self.lookup
        else:
            path, sep, last_part = self.lookup.rpartition(LOOKUP_SEP)
            return path + sep + self.to_attr
    lookup_refpath = property(_lookup_refpath)

    def get_current_lookup(self, level):
        """
        Returns the first level + 1 parts of the self.lookup_refpath
        """
        parts = self.lookup_refpath.split(LOOKUP_SEP)
        return LOOKUP_SEP.join(parts[0:level + 1])

    def get_to_attr(self, level):
        """
        Returns information about into what attribute should the results be
        fetched, and if that attribute is related object manager, or will the
        objects be fetched into a list.
        """
        parts = self.lookup_refpath.split(LOOKUP_SEP)
        if self.to_attr is None or level < len(parts) - 1:
            return parts[level], False
        else:
            return self.to_attr, True
