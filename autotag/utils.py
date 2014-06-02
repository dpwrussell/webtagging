import omero
import os
from omero.rtypes import rlong

def parse_path(path):
    # TODO Should take arguments relating to regex
    """ 
    Splits the path up according to regex and returns lists of tokens
    per seperator.
    Hardcoded for now, one for the path, one for the name, one for the extension
    """

    # Split by '/' to get the path, then by '_'
    path_tokens = []
    temp_tokens = path.split(r'/')
    file = temp_tokens.pop()
    for token in temp_tokens:
        path_tokens.extend(token.split(r'_'))

    # Split by first '.' to get the extension (considered to be everything
    # after the first '.'), then by '_'
    ext_tokens = []
    temp_tokens = file.rsplit(r'.')
    file = temp_tokens.pop(0)
    for token in temp_tokens:
        ext_tokens.extend(token.split(r'_'))

    #TODO Cope with multiple separators
    file_tokens = file.split(r'_')

    return path_tokens, file_tokens, ext_tokens

def createTagAnnotationsLinks(conn, additions=[], removals=[]):
    """
    Links or unlinks existing Images with existing Tag annotations 
    
    @param additions:       List of tags to add to images
    @param additions:       List of tags to remove from images
    """

    newLinks = []        
    # Create a list of links to apply
    for addition in additions:
        link = omero.model.ImageAnnotationLinkI()
        link.parent = omero.model.ImageI(addition[0], False)
        link.child = omero.model.TagAnnotationI(addition[1], False)
        newLinks.append(link)

    # Apply the links
    failed = 0
    savedLinks = []
    try:
        # will fail if any of the links already exist
        savedLinks = conn.getUpdateService().saveAndReturnArray(
            newLinks,
            conn.SERVICE_OPTS
        )
    except omero.ValidationException, x:
        # This will occur if the user has modified the tag landscape outside
        # of the auto-tagger while using the auto-tagger. Not likely to often
        # happen, but very possible.

        for link in newLinks:
            try:
                savedLinks.append(conn.getUpdateService().saveAndReturnObject(
                    link,
                    conn.SERVICE_OPTS)
                )
            except omero.ValidationException, x2:
                failed+=1

    if len(removals) > 0:
        # Get existing links belonging to current user (all at once to save
        # on queries)
        allImageIds, allTagIds, allTokenNames = zip(*removals)

        # removalsCheck has to exist because the check to see if the
        # image/tagId combo was in the list, there is no knowledge of the
        # tokenName
        removalsCheck = zip(allImageIds, allTagIds)
        params = omero.sys.Parameters()
        params.theFilter = omero.sys.Filter()
        params.theFilter.ownerId = rlong(conn.getUserId())
        links = conn.getAnnotationLinks("Image",
                                        parent_ids=list(allImageIds),
                                        ann_ids=list(allTagIds),
                                        params=params)

        # The above returns image->tag links that were not specified for
        # deletion, so only delete the appropriate ones 
        for link in links:
            if (link.parent.id.val, link.child.id.val) in removalsCheck:
                conn.deleteObjectDirect(link._obj)


class ImageWrapper (omero.gateway.ImageWrapper):
    """
    omero_model_ImageI class wrapper overwrite omero.gateway.ImageWrapper
    """

    def getClientPath(self):
        qs = self._conn.getQueryService()
        params = omero.sys.ParametersI()
        params.addLong("iid", self.getId())
        query = "select fse from FilesetEntry fse join fse.fileset as fs "\
                "left outer join fs.images as image where image.id=:iid"

        # this could be OMERO 4, so handle that
        try:
            r = qs.findAllByQuery(query, params, self._conn.SERVICE_OPTS)
            paths = [fs.clientPath.val for fs in r]
            path = os.path.commonprefix(paths)
        except:
            path = ""
        return path

# Update the ref to ImageWrapper in BlitzGateway
omero.gateway.ImageWrapper = ImageWrapper


class BlitzSet(object):
    """
    Custom set to contain omero blitz objects using the id as the unique
    identifier.

    This has a subset of set operations

    Warning: This should not be used as-is for sets of objects that do not
    have ids yet (i.e. new objects). It should also not be used if there is
    any manipulation of the ids within the blitz objects although I'm unsure
    if there is ever likely to be any reason to do this.

    Effort has been made to ensure that BlitzSet behaves the same as the python
    built-in set. For example, adding an item to a set which already exists
    results in the original item being kept and the new item being discarded.
    This could be important if using this set and manipulating the contents of
    blitz objects. For example, the following example could happen:

    tags = BlitzSet([])
    tag1 = conn.getObject('TagAnnotation', 1)
    tags.add(tag1)
    tag2 = conn.getObject('TagAnnotation', 1)
    tag2.setValue("TEST")
    tags.add(tag2)

    tag1 and tag2 are 2 completely separate objects that to BlitzSet are seen
    as identical. In this case, the single item in the set would be tag1, not
    tag2.

    """
    def __init__(self, s=[]):

        self.__items = dict(
            (self.__item_key(i), i) for
             i in s
        )

    def __item_key(self, item):
        return item.getId()

    def add(self, item):
        """
        Add item to set

        To be consistent with python set, do not overwrite existing items
        """

        if not self.__contains__(item):
            self.__items[self.__item_key(item)] = item

    def remove(self, item):
        """
        Remove item from set
        """

        del self.__items[self.__item_key(item)]

    def update(self, items):
        """
        Add a collection of items to the set

        Unlike add, update overwrites existing items
        """

        for item in items:
            self.__items[self.__item_key(item)] = item

    def union(self, other):
        """
        Union of this set with specified other set

        To be consistent with python set, self overrides other
        """

        uni = BlitzSet()
        uni.__items = dict(other.__items, **self.__items)
        return uni

    def __or__(self, other):
        """
        Union using || operator
        """

        return self.union(other)

    def intersection(self, other):
        """
        Intersection of this set with specified other set

        To be consistent with python set, shorter list overrides
        or the other set if equal length
        """

        # Determine shorter list for iteration
        if len(self.__items) < len(other.__items):
            s1 = self.__items
            s2 = other.__items
        else:
            s1 = other.__items
            s2 = self.__items

        # Compute the intersection
        inter = BlitzSet()
        for k in s1.iterkeys():
            if k in s2:
                inter.add(s1[k])
        return inter

    def __and__(self, other):
        """
        Intersection using && operator
        """

        return self.intersection(other)

    def difference(self, other):
        """
        Difference of this set and specified other set
        """

        inter = BlitzSet()
        for k in self.__items.iterkeys():
            if k not in other.__items:
                inter.add(self.__items[k])
        return inter

    def __sub__(self, other):
        """
        Difference using - operator
        """

        return self.difference(other)

    def symmetric_difference(self, other):
        """
        Symmetric difference of this set and specified other set
        """

        # TODO Performance wise, probably not optimal
        diff1 = self.difference(other)
        diff2 = other.difference(self)
        return diff1.union(diff2)

    def __xor__(self, other):
        """
        Symmetric difference using ^ operator
        """

        return self.symmetric_difference(other)

    def __str__(self):
        return str(self.__items.values())

    def __contains__(self, item):
        return self.__item_key(item) in self.__items

    def __iter__(self):
        return self.__items.itervalues()

    def __len__(self):
        return len(self.__items)