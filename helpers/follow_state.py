"""Existing Users.following is the source of outgoing social edges, scoped by DB."""


def ids(value):
    return set(x for x in (value or []) if isinstance(x, str))


def relation_bits(row, viewer_uid, outgoing=None):
    if not viewer_uid or row.get("id") == viewer_uid:
        return 0
    follows = (
        viewer_uid in ids(row.get("whoFollows"))
        if outgoing is None
        else row.get("id") in outgoing
    )
    return int(follows) + 2 * int(viewer_uid in ids(row.get("following")))


async def project_profiles(db, ndc_id, viewer_uid, profiles):
    if not profiles:
        return profiles
    table = db.get(f"x{ndc_id}", "Users")
    target_ids = list({p["uid"] for p in profiles if p.get("uid")})
    viewer = (
        await table.find_one({"id": viewer_uid}, {"following": 1})
        if viewer_uid
        else None
    )
    outgoing = ids((viewer or {}).get("following"))
    rows = {
        row["id"]: row
        async for row in table.find(
            {"id": {"$in": target_ids}}, {"id": 1, "following": 1}
        )
    }
    counts = {
        row["_id"]: row["n"]
        async for row in table.aggregate(
            [
                {
                    "$match": {
                        "following": {"$in": target_ids},
                        "status": {"$nin": [5, 9, 10]},
                    }
                },
                {
                    "$project": {
                        "targets": {
                            "$setIntersection": [
                                {"$ifNull": ["$following", []]},
                                target_ids,
                            ]
                        }
                    }
                },
                {"$unwind": "$targets"},
                {"$group": {"_id": "$targets", "n": {"$sum": 1}}},
            ]
        )
    }
    result = []
    for profile in profiles:
        row = rows.get(profile.get("uid"))
        if row is None:
            result.append(profile)
            continue
        bits = relation_bits(row, viewer_uid, outgoing)
        result.append(
            dict(
                profile,
                followingStatus=bits,
                membershipStatus=bits,
                membersCount=counts.get(row["id"], 0),
                joinedCount=len(ids(row.get("following")) - {row["id"]}),
            )
        )
    return result


async def project_profile(db, ndc_id, viewer_uid, profile):
    return (await project_profiles(db, ndc_id, viewer_uid, [profile]))[0]
